import yaml
import os
import re
import logging

logger = logging.getLogger(__name__)

def load_config_callback(ctx, param, value):
    """
    Eager callback that reads the dbt-ci YAML config file and injects its values
    into os.environ before Click resolves the remaining options.

    Keys in the config file should match Click envvar names (e.g. DBT_RUNNER).
    Actual shell environment variables always take precedence (setdefault).

    Values of the form ${VAR_NAME} are resolved from the current environment.

    Example config (dbt-ci.config.yaml):
        DBT_RUNNER: docker
        DBT_DOCKER_IMAGE: europe-west1-docker.pkg.dev/my-project/dbt
        DBT_PROJECT_DIR: dbt
        DBT_DOCKER_ENV: "DBT_PROFILES_DIR=/dbt,GOOGLE_APPLICATION_CREDENTIALS=${GOOGLE_APPLICATION_CREDENTIALS}"
    """

    def _resolve(val: str) -> str:
        """Replace ${VAR} references with their current environment values."""
        def replacer(match):
            var_name = match.group(1)
            return os.environ.get(var_name, match.group(0))  # keep original if not found
        return re.sub(r'\$\{([^}]+)\}', replacer, val)

    if not value:
        return value
    try:
        if os.path.exists(value) is False:
            return value

        logger.info(f"Configuration file found. Loading configuration from {value}")

        with open(value, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        for key, val in config.items():
            if val is not None:
                if isinstance(val, list):
                    resolved = ",".join(_resolve(str(item)) for item in val)
                else:
                    resolved = _resolve(str(val))
                os.environ.setdefault(str(key), resolved)
    except Exception:
        logger.debug(f"No valid config file found at {value} or error reading file - proceeding with environment variables and defaults.")
        pass  # Config file issues should not crash the CLI
    return value