import yaml
import os
import re
import logging
from typing import Any
import click

logger = logging.getLogger(__name__)

# Key used to store the parsed config dict in Click's context metadata
_CTX_META_KEY = "dbt_ci_config"


def _resolve_env_refs(val: str) -> str:
    """Replace ${VAR} references with their current environment values."""
    def replacer(match: re.Match) -> str:
        return os.environ.get(match.group(1), match.group(0))
    return re.sub(r'\$\{([^}]+)\}', replacer, val)


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
        upper_key = key.upper()
        if isinstance(val, dict):
            # Recurse into nested block, e.g. docker: { image: ... }
            # The nested key becomes the new prefix: docker -> DBT_DOCKER
            nested_prefix = f"DBT_{upper_key}" if not prefix else f"{prefix}_{upper_key}"
            flat.update(_flatten_config(val, prefix=nested_prefix))
        else:
            # Top-level key: if it doesn't already start with a known prefix, prepend DBT_
            if prefix:
                env_key = f"{prefix}_{upper_key}"
            elif upper_key.startswith("DBT_") or upper_key.startswith("SLACK_"):
                env_key = upper_key  # already a full env var name
            else:
                env_key = f"DBT_{upper_key}"
            flat[env_key] = val
    return flat


def load_config_callback(ctx, param, value):
    """
    Eager callback that reads the dbt-ci YAML config file.

    - Stores the parsed flat config in ctx.meta so individual option callbacks
      can read it via make_config_callback().
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
    if not value:
        return value
    try:
        if not os.path.exists(value):
            return value

        logger.info(f"Configuration file found. Loading configuration from {value}")

        with open(value, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        flat = _flatten_config(raw)

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

    except Exception:
        logger.debug(
            f"No valid config file found at {value} or error reading it — "
            "proceeding with environment variables and defaults."
        )

    print("Load Config:", ctx.meta.get(_CTX_META_KEY, {}))  # Debug print to verify loaded config
    return value


def make_config_callback(config_key: str, *, then=None):
    """
    Return a Click option callback that resolves values with the priority:

        CLI flag  >  config file  >  env var  >  default

    Args:
        config_key: The env var key to look up in the parsed config
                    (e.g. 'DBT_RUNNER', 'DBT_DOCKER_IMAGE').
        then: Optional callable to apply to the resolved value (e.g. str.upper).
              Receives (value) and returns the transformed value.

    Usage:
        click.option('--runner', envvar=['DBT_RUNNER'], callback=make_config_callback('DBT_RUNNER'))
    """
    def callback(ctx, param, value):
        source = ctx.get_parameter_source(param.name)

        # Explicit CLI flag always wins
        if source == click.core.ParameterSource.COMMANDLINE:
            return then(value) if then else value

        # Config file is next
        config: dict[str, Any] = ctx.meta.get(_CTX_META_KEY, {})
        if config_key in config:
            config_val = config[config_key]
            # For multiple/tuple options, return a tuple
            if param.multiple and isinstance(config_val, list):
                result = tuple(config_val)
            elif param.multiple and isinstance(config_val, str):
                result = tuple(p.strip() for p in config_val.replace('\n', ',').split(',') if p.strip())
            elif isinstance(config_val, bool):
                result = config_val
            else:
                try:
                    result = param.type.convert(config_val, param, ctx)
                except Exception:
                    result = config_val
            return then(result) if then else result

        # Fall back to Click's resolved value (env var or default)
        return then(value) if then else value

    return callback
