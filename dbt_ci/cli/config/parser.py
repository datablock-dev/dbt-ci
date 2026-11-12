import json
import yaml
import os
import re
import sys
import logging
from typing import Any
import click

from dbt_ci.utilities.ci_event import PUSH, resolve_event
from dbt_ci.utilities.paths import get_cache_dir
from .schema import validate_config

logger = logging.getLogger(__name__)

_CTX_META_KEY = "dbt_ci_config"
# The parsed config file and the selected profile, kept until both eager callbacks ran
_CTX_RAW_KEY = "dbt_ci_raw_config"
_CTX_PROFILE_KEY = "dbt_ci_profile"
# The --event override, and the event the config was resolved for (name, reason)
_CTX_EVENT_ARG_KEY = "dbt_ci_event_arg"
_CTX_EVENT_KEY = "dbt_ci_event"
# Where values came from, for `dbt-ci config show`: the config file path, the layer each
# flat key came from, the keys injected into os.environ, and per option which layer won
_CTX_PATH_KEY = "dbt_ci_config_path"
_CTX_ORIGIN_KEY = "dbt_ci_config_origin"
_CTX_INJECTED_KEY = "dbt_ci_config_injected"
_CTX_SOURCES_KEY = "dbt_ci_option_sources"

# Labels for the config file layers
TOP_LEVEL = "config file"
# The config file key holding per-event settings. YAML 1.1 (PyYAML) reads a bare `on`
# key as the boolean true, as GitHub Actions users know, so that spelling is accepted too.
EVENTS_KEY = "on"
# The key in an `on: push:` block listing the deploy branches; not a setting itself
BRANCHES_KEY = "branches"


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


def event_callback(ctx, param, value):
    """Eager callback that records an explicit --event, applied once the config is read."""
    ctx.meta[_CTX_EVENT_ARG_KEY] = value or None
    _apply_config_when_ready(ctx)
    return value or None


def _base_ref(ctx, flat: dict[str, Any]) -> str | None:
    """
    Return the default branch for telling pushes apart, before options are parsed.

    In order: --base-ref on the command line, DBT_CI_BASE_REF, init.base-ref in the config
    file, then (for commands after init) the base ref init recorded.
    """
    argv = sys.argv[1:]
    for i, arg in enumerate(argv):
        if arg == "--base-ref" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--base-ref="):
            return arg.split("=", 1)[1] or None
    from_config = os.environ.get("DBT_CI_BASE_REF") or _text(flat.get("DBT_INIT_BASE_REF"))
    if from_config or ctx.command.name == "init":
        return from_config
    return _recorded_by_init("reference", "base_ref")


def _profile_recorded_by_init() -> str | None:
    """Return the profile init recorded in its cache, or None when there isn't one."""
    return _recorded_by_init("profile")


def _recorded_by_init(*path: str) -> str | None:
    """Return a setting from the config block init recorded in its cache, if any."""
    cache_file = get_cache_dir() / "cache.json"
    try:
        with open(cache_file, encoding="utf-8") as f:
            value: Any = (json.load(f) or {}).get("config") or {}
    except (OSError, ValueError, AttributeError):
        return None
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value if isinstance(value, str) and value else None


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
        raw = normalize_event_keys(raw)

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
    has_event_option = any(p.name == "event" for p in ctx.command.params)
    if has_event_option and _CTX_EVENT_ARG_KEY not in ctx.meta:
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
    ctx.meta[_CTX_PATH_KEY] = path
    flat = _flatten_config(_settings(raw))
    origin = {env_key: TOP_LEVEL for env_key in flat}
    if profile:
        profiles = raw.get("profiles") or {}
        if profile in profiles:
            logger.info(f"Applying config profile '{profile}' from {path}")
            # Flattening each side first makes a profile's value replace the top-level
            # one whichever spelling (project-dir, project_dir, DBT_PROJECT_DIR) each uses
            profile_flat = _flatten_config(_settings(profiles[profile] or {}))
            flat.update(profile_flat)
            origin.update({env_key: f"profile '{profile}'" for env_key in profile_flat})
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

    # Settings for the event this run is for go over the profile: first the top-level
    # `on:` block, then the selected profile's own
    profile_raw = ((raw.get("profiles") or {}).get(profile) or {}) if profile else {}
    blocks = [(raw.get(EVENTS_KEY) or {}, None), (profile_raw.get(EVENTS_KEY) or {}, profile)]
    override = ctx.meta.get(_CTX_EVENT_ARG_KEY)
    if override or any(blocks_for for blocks_for, _ in blocks):
        try:
            event = resolve_event(
                override,
                base_branch=_base_ref(ctx, flat),
                push_branches=_push_branches(raw, profile_raw),
            )
        except ValueError as e:
            raise click.BadParameter(str(e), param_hint="'--event'")
        ctx.meta[_CTX_EVENT_KEY] = (event.name, event.reason)
        logger.info(f"Event: {event.name or 'none'} ({event.reason})")
        for block, block_profile in blocks:
            if event.name and block.get(event.name):
                event_flat = _flatten_config(_settings(block[event.name]))
                flat.update(event_flat)
                label = f"event '{event.name}'"
                if block_profile:
                    label = f"profile '{block_profile}', {label}"
                origin.update({env_key: label for env_key in event_flat})

    # Resolve ${VAR} references and store in ctx.meta. An empty value, whether written
    # as "" or left by a ${VAR} that is set but empty, counts as not set, like null.
    resolved: dict[str, Any] = {}
    for env_key, val in flat.items():
        if val is None:
            continue
        if isinstance(val, list):
            resolved[env_key] = [_resolve_env_refs(str(item)) for item in val]
        elif isinstance(val, bool):
            resolved[env_key] = val
        else:
            text = _resolve_env_refs(str(val))
            if text.strip():
                resolved[env_key] = text

    ctx.meta[_CTX_META_KEY] = resolved
    ctx.meta[_CTX_ORIGIN_KEY] = origin

    # Backward-compat: also inject into os.environ for options without make_config_callback
    injected: set[str] = set()
    for env_key, val in resolved.items():
        if env_key not in os.environ:
            injected.add(env_key)
        if isinstance(val, list):
            os.environ.setdefault(env_key, ",".join(val))
        else:
            os.environ.setdefault(env_key, str(val))
    ctx.meta[_CTX_INJECTED_KEY] = injected

    logger.debug("Load Config: %s", resolved)


def normalize_event_keys(raw: Any) -> Any:
    """Rename a boolean `true` key (how PyYAML reads `on:`) to "on", here and in profiles."""
    if not isinstance(raw, dict):
        return raw
    fixed = {(EVENTS_KEY if key is True else key): value for key, value in raw.items()}
    profiles = fixed.get("profiles")
    if isinstance(profiles, dict):
        fixed["profiles"] = {name: normalize_event_keys(body) for name, body in profiles.items()}
    return fixed


def _settings(raw: dict) -> dict:
    """Return a config mapping without its profiles, per-event blocks and push branches."""
    return {k: v for k, v in raw.items() if k not in ("profiles", EVENTS_KEY, BRANCHES_KEY)}


def _push_branches(raw: dict, profile_raw: dict) -> list[str] | None:
    """
    Return the branches a push must be to, or None for the default branch only.

    The selected profile's `on.push.branches` replaces the top-level list as a whole.
    ${VAR} references are resolved, and a list left empty counts as not set.
    """
    for config in (profile_raw, raw):
        value = ((config.get(EVENTS_KEY) or {}).get(PUSH) or {}).get(BRANCHES_KEY)
        items = [value] if isinstance(value, str) else value or []
        patterns = [text for item in items if (text := _resolve_env_refs(str(item)).strip())]
        if patterns:
            return patterns
    return None


def _text(value: Any) -> str | None:
    """Return a config value as a non-empty string, or None."""
    return str(value) if value not in (None, "") else None


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
            origin: dict[str, str] = ctx.meta.get(_CTX_ORIGIN_KEY, {})
            ctx.meta.setdefault(_CTX_SOURCES_KEY, {})[param.name] = origin.get(found, TOP_LEVEL)
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


def config_provenance(ctx) -> dict[str, Any]:
    """
    Return what a context recorded about where its settings came from.

    Keys: path (the config file, or None), profile and profile_inherited, origin (the
    layer each flat config key came from), injected (config keys copied into os.environ)
    and sources (the config layer that set each option, by parameter name).
    """
    profile, inherited = ctx.meta.get(_CTX_PROFILE_KEY, (None, False))
    return {
        "path": ctx.meta.get(_CTX_PATH_KEY),
        "profile": profile,
        "profile_inherited": inherited,
        "origin": ctx.meta.get(_CTX_ORIGIN_KEY, {}),
        "injected": ctx.meta.get(_CTX_INJECTED_KEY, set()),
        "sources": ctx.meta.get(_CTX_SOURCES_KEY, {}),
        "event": ctx.meta.get(_CTX_EVENT_KEY),
    }
