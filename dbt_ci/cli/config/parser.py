import json
import yaml
import os
import re
import sys
import logging
from typing import Any
import click

from dbt_ci.utilities.paths import get_cache_dir
from .schema import validate_config

logger = logging.getLogger(__name__)

_CTX_META_KEY = "dbt_ci_config"
# The parsed config file and the selected profile, kept until both eager callbacks ran
_CTX_RAW_KEY = "dbt_ci_raw_config"
_CTX_PROFILE_KEY = "dbt_ci_profile"


def _resolve_env_refs(val: str) -> str:
    """Replace ${VAR} references with their current environment values."""

    def replacer(match: re.Match) -> str:
        return os.environ.get(match.group(1), match.group(0))

    return re.sub(r"\$\{([^}]+)\}", replacer, val)


def _flatten_config(raw: dict, prefix: str = "") -> dict[str, Any]:
    """
    Flatten a potentially nested config dict into a flat dict keyed by env var names.

    Supports two config styles:

    Flat (legacy):
        DBT_RUNNER: docker
        DBT_DOCKER_IMAGE: my-image

    Nested (new):
        runner: docker
        docker:
          image: my-image
          volumes:
            - dbt:/dbt:rw

    Nested keys are flattened with the 'DBT_' prefix and uppercased:
        runner        -> DBT_RUNNER
        docker.image  -> DBT_DOCKER_IMAGE
        docker.volumes -> DBT_DOCKER_VOLUMES
    """
    flat: dict[str, Any] = {}
    for key, val in raw.items():
        upper_key = key.upper().replace("-", "_")
        if isinstance(val, dict):
            nested_prefix = f"DBT_{upper_key}" if not prefix else f"{prefix}_{upper_key}"
            flat.update(_flatten_config(val, prefix=nested_prefix))
        else:
            if prefix and upper_key.startswith(f"{prefix}_"):
                # A field already written with its full name (docker: {DBT_DOCKER_PLATFORM: x})
                env_key = upper_key
            elif prefix:
                env_key = f"{prefix}_{upper_key}"
            elif upper_key.startswith("DBT_") or upper_key.startswith("SLACK_"):
                env_key = upper_key
            else:
                env_key = f"DBT_{upper_key}"
            flat[env_key] = val
    return flat


def load_config_callback(ctx, param, value):
    """
    Eager callback that reads the dbt-ci YAML config file.

    - Validates the raw config against the schema and raises an error on any issues.
    - Once the profile is known too (see profile_callback), merges the selected profile
      over the top-level settings and stores the flat result in ctx.meta, so individual
      option callbacks can read it via make_config_callback().
    - Also injects values into os.environ (using setdefault) for backward
      compatibility with options that don't use make_config_callback.

    Supports both flat (legacy) and nested (new) config styles. Keys are
    case-insensitive and lowercased keys are automatically mapped to their
    DBT_ env var equivalents.

    Example (nested style):
        runner: docker
        project_dir: dbt
        docker:
          image: my-registry/dbt:latest
          volumes:
            - dbt:/dbt:rw
          env:
            - DBT_STATE=${DBT_STATE}
    """
    ctx.meta[_CTX_RAW_KEY] = _read_config_file(value)
    _apply_config_when_ready(ctx)
    return value


def profile_callback(ctx, param, value):
    """
    Eager callback that records which config profile to apply.

    Every command except init falls back to the profile init ran with, recorded in the
    cache, so a profile chosen once for init carries through run, report and the rest.
    Returns the profile actually used, so commands (and init's cache) can see it.
    """
    inherited = False
    if not value and ctx.command.name != "init":
        value = _profile_recorded_by_init()
        inherited = value is not None
    ctx.meta[_CTX_PROFILE_KEY] = (value or None, inherited)
    _apply_config_when_ready(ctx)
    return value or None


def _profile_recorded_by_init() -> str | None:
    """Return the profile init recorded in its cache, or None when there isn't one."""
    cache_file = get_cache_dir() / "cache.json"
    try:
        with open(cache_file, encoding="utf-8") as f:
            cached = json.load(f)
    except (OSError, ValueError):
        return None
    profile = ((cached or {}).get("config") or {}).get("profile")
    return profile if isinstance(profile, str) and profile else None


def _read_config_file(value: str | None) -> tuple[str, dict] | None:
    """Find, parse and validate the config file, returning its path and raw contents."""
    if not value:
        return None
    try:
        if not os.path.exists(value):
            # Config not found in CWD — try to locate it relative to --dbt-project-dir.
            # The config callback fires eagerly before other options are parsed, so we
            # peek at DBT_PROJECT_DIR from the environment and sys.argv as a fallback.
            project_dir = os.environ.get("DBT_PROJECT_DIR")
            if project_dir is None:
                argv = sys.argv[1:]
                for i, arg in enumerate(argv):
                    if arg == "--dbt-project-dir" and i + 1 < len(argv):
                        project_dir = argv[i + 1]
                        break
            if project_dir:
                candidate = os.path.join(project_dir, value)
                if os.path.exists(candidate):
                    logger.info(f"Config not found in CWD, using {candidate}")
                    value = candidate
                else:
                    return None
            else:
                return None

        logger.info(f"Configuration file found. Loading configuration from {value}")

        with open(value, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        errors = validate_config(raw)
        if errors:
            error_list = "\n".join(f"  - {e}" for e in errors)
            raise click.BadParameter(
                f"Config file '{value}' has validation errors:\n{error_list}",
                param_hint="'--config'",
            )
        return value, raw

    except click.BadParameter:
        raise
    except yaml.YAMLError as e:
        raise click.BadParameter(
            f"Config file '{value}' contains invalid YAML: {e}",
            param_hint="'--config'",
        )
    except Exception as e:
        raise click.BadParameter(
            f"Failed to load config file '{value}': {e}",
            param_hint="'--config'",
        )


def _apply_config_when_ready(ctx) -> None:
    """
    Resolve the config once both the file and the profile are known.

    --config and --profile are both eager, and Click processes eager options in the
    order they appear on the command line, so either callback can run first. A command
    without a --profile option applies the file as soon as it is read.
    """
    if _CTX_META_KEY in ctx.meta or _CTX_RAW_KEY not in ctx.meta:
        return
    has_profile_option = any(p.name == "profile" for p in ctx.command.params)
    if has_profile_option and _CTX_PROFILE_KEY not in ctx.meta:
        return

    profile, inherited = ctx.meta.get(_CTX_PROFILE_KEY, (None, False))
    loaded = ctx.meta[_CTX_RAW_KEY]
    if loaded is None:
        if profile and not inherited:
            raise click.BadParameter(
                f"Profile '{profile}' was requested, but no dbt-ci config file was found.",
                param_hint="'--profile'",
            )
        ctx.meta[_CTX_META_KEY] = {}
        return

    path, raw = loaded
    flat = _flatten_config({k: v for k, v in raw.items() if k != "profiles"})
    if profile:
        profiles = raw.get("profiles") or {}
        if profile in profiles:
            logger.info(f"Applying config profile '{profile}' from {path}")
            # Flattening each side first makes a profile's value replace the top-level
            # one whichever spelling (project-dir, project_dir, DBT_PROJECT_DIR) each uses
            flat.update(_flatten_config(profiles[profile] or {}))
        elif inherited:
            logger.warning(
                f"Ignoring profile '{profile}' recorded by init: it is not defined in {path}."
            )
        else:
            available = ", ".join(sorted(profiles)) or "none"
            raise click.BadParameter(
                f"Profile '{profile}' is not defined in '{path}'. Available profiles: "
                f"{available}.",
                param_hint="'--profile'",
            )

    # Resolve ${VAR} references and store in ctx.meta
    resolved: dict[str, Any] = {}
    for env_key, val in flat.items():
        if val is None:
            continue
        if isinstance(val, list):
            resolved[env_key] = [_resolve_env_refs(str(item)) for item in val]
        elif isinstance(val, bool):
            resolved[env_key] = val
        else:
            resolved[env_key] = _resolve_env_refs(str(val))

    ctx.meta[_CTX_META_KEY] = resolved

    # Backward-compat: also inject into os.environ for options without make_config_callback
    for env_key, val in resolved.items():
        if isinstance(val, list):
            os.environ.setdefault(env_key, ",".join(val))
        else:
            os.environ.setdefault(env_key, str(val))

    logger.debug("Load Config: %s", resolved)


def make_config_callback(config_key: str | tuple[str, ...], *, then=None):
    """
    Return a Click option callback that resolves values with the priority:

        CLI flag  >  config file  >  env var  >  default

    Args:
        config_key: The env var key to look up in the parsed config
                    (e.g. 'DBT_RUNNER', 'DBT_DOCKER_IMAGE'), or several keys in
                    priority order when an option has a legacy spelling too.
        then: Optional callable to apply to the resolved value (e.g. str.upper).
              Receives (value) and returns the transformed value.

    Usage:
        click.option('--runner', envvar=['DBT_RUNNER'], callback=make_config_callback('DBT_RUNNER'))
    """

    def callback(ctx, param, value):
        source = ctx.get_parameter_source(param.name)

        if source == click.core.ParameterSource.COMMANDLINE:
            return then(value) if then else value

        config: dict[str, Any] = ctx.meta.get(_CTX_META_KEY, {})
        keys = (config_key,) if isinstance(config_key, str) else config_key
        found = next((key for key in keys if key in config), None)
        if found is not None:
            config_val = config[found]
            result: Any
            if param.multiple and isinstance(config_val, list):
                result = tuple(config_val)
            elif param.multiple and isinstance(config_val, str):
                result = tuple(
                    p.strip() for p in config_val.replace("\n", ",").split(",") if p.strip()
                )
            elif isinstance(config_val, bool):
                result = config_val
            else:
                try:
                    result = param.type.convert(config_val, param, ctx)
                except Exception:
                    result = config_val
            return then(result) if then else result

        return then(value) if then else value

    return callback
