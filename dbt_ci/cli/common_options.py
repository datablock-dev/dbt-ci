import os
import re
import click
from dbt_ci.cli.config import load_config_callback, make_config_callback

# Values accepted in DEFER_FLAG. Pipelines usually hold the literal dbt flag in it
# ("--defer" or empty) so it can be spliced into a dbt command, so both styles count.
_DEFER_FLAG_TRUE = {"--defer", "true", "1", "yes", "y", "on"}
_DEFER_FLAG_FALSE = {"", "--no-defer", "false", "0", "no", "n", "off"}


def parse_defer_flag(value: str) -> bool:
    """Turn a DEFER_FLAG value such as "--defer", "" or "true" into a boolean."""
    normalised = value.strip().lower()
    if normalised in _DEFER_FLAG_TRUE:
        return True
    if normalised in _DEFER_FLAG_FALSE:
        return False
    raise click.BadParameter(
        f"DEFER_FLAG must be '--defer', '--no-defer', empty or a boolean, got {value!r}",
        param_hint="'DEFER_FLAG'",
    )


def make_defer_callback():
    """
    Resolve --defer like make_config_callback("DBT_DEFER"), with DEFER_FLAG as a fallback.

    DEFER_FLAG is only read when neither the CLI flag, the config file nor DBT_DEFER
    sets a value, so the order is CLI flag > config file > DBT_DEFER > DEFER_FLAG > default.
    """
    resolve = make_config_callback("DBT_DEFER")

    def callback(ctx, param, value):
        """Fall back to DEFER_FLAG when --defer was left at its default."""
        if ctx.get_parameter_source(param.name) == click.core.ParameterSource.DEFAULT:
            defer_flag = os.environ.get("DEFER_FLAG")
            if defer_flag is not None:
                value = parse_defer_flag(defer_flag)
        return resolve(ctx, param, value)

    return callback


class NewlineSeparatedString(click.types.StringParamType):
    """A string option whose environment variable is split on newlines only, not whitespace."""

    envvar_list_splitter = "\n"


# click splits a multiple option's environment variable on whitespace by default, which
# cut values such as "A=hello world" in two and silently dropped the second half.
NEWLINE_SEPARATED = NewlineSeparatedString()

# A comma only separates two entries when the next one starts a new KEY=, so commas
# inside a value (e.g. DBT_VARS={"a": 1, "b": 2}) are kept.
_ENV_ENTRY_SEPARATOR = re.compile(r",(?=\s*[A-Za-z_][A-Za-z0-9_]*=)")

# dbt-ci and dbt both read DBT_LOG_LEVEL, but dbt only accepts its own lowercase names.
_DBT_LOG_LEVELS = {
    "DEBUG": "debug",
    "INFO": "info",
    "WARNING": "warn",
    "WARN": "warn",
    "ERROR": "error",
    "CRITICAL": "error",
    "NONE": "none",
}


# dbt's spellings mapped to the Python logging level dbt-ci itself uses
_PYTHON_LOG_LEVELS = {"WARN": "WARNING", "NONE": "CRITICAL"}


def normalise_log_level(value: str) -> str:
    """
    Return dbt-ci's Python log level and rewrite DBT_LOG_LEVEL into a value dbt accepts.

    The config file copies log-level into DBT_LOG_LEVEL, which dbt (in-process or as a
    subprocess) also reads; "WARNING" or "CRITICAL" there made every dbt call fail.
    """
    env_value = os.environ.get("DBT_LOG_LEVEL")
    if env_value:
        os.environ["DBT_LOG_LEVEL"] = _DBT_LOG_LEVELS.get(env_value.strip().upper(), env_value)
    level = value.upper()
    return _PYTHON_LOG_LEVELS.get(level, level)


def parse_env_option(value):
    """
    Normalise --docker-env values into a tuple of KEY=VALUE entries.

    Like parse_multiple_option, but a comma only splits entries when it is followed by
    another KEY=, so values that contain commas themselves stay intact.
    """
    if not value:
        return value
    entries: list[str] = []
    for item in (value if isinstance(value, (list, tuple)) else [value]):
        for line in str(item).split("\n"):
            entries.extend(part.strip() for part in _ENV_ENTRY_SEPARATOR.split(line) if part.strip())
    return tuple(entries)


def parse_multiple_option(value):
    """
    Normalise a multiple-value option by splitting comma/newline-separated
    strings (from env vars or config file) into a tuple.

    Examples:
        ('KEY1=val1,KEY2=val2',)                       -> ('KEY1=val1', 'KEY2=val2')
        ('KEY1=val1\\nKEY2=val2',)                      -> ('KEY1=val1', 'KEY2=val2')
        ('KEY1=val1', 'KEY2=val2')                     -> ('KEY1=val1', 'KEY2=val2') (unchanged)
    """
    if not value:
        return value
    if isinstance(value, (list, tuple)) and len(value) == 1 and (',' in value[0] or '\n' in value[0]):
        return tuple(p.strip() for p in value[0].replace('\n', ',').split(',') if p.strip())
    return value if isinstance(value, tuple) else tuple(value)


COMMON_OPTIONS = [
    click.option(
        "--config", "-c",
        envvar=["DBT_CONFIG"],
        default="dbt-ci.config.yaml",
        is_eager=True,
        callback=load_config_callback,
        help=(
            "Path to dbt-ci configuration file (YAML). Supports flat (DBT_RUNNER: docker) "
            "and nested (docker: {image: ...}) styles. Precedence: CLI flag > config file > env var > default."
        ),
    ),
    click.option(
        "--dbt-version",
        envvar=["DBT_VERSION"],
        default=None,
        callback=make_config_callback("DBT_VERSION"),
        help="Specify a dbt version to use for this command",
    ),
    click.option(
        "--adapter", "-a",
        envvar=["DBT_ADAPTER"],
        type=str,
        default=None,
        callback=make_config_callback("DBT_ADAPTER"),
        help="Specify the dbt adapter to use (e.g., 'postgres', 'snowflake')",
    ),
    click.option(
        "--dbt-project-dir",
        envvar=["DBT_PROJECT_DIR"],
        default=".",
        callback=make_config_callback("DBT_PROJECT_DIR"),
        help="Path to the dbt project directory (default: current directory)",
    ),
    click.option(
        "--profiles-dir",
        envvar=["DBT_PROFILES_DIR"],
        default=None,
        callback=make_config_callback("DBT_PROFILES_DIR"),
        help="Path to the directory containing the dbt profiles.yml file",
    ),
    click.option(
        "--reference-state", "--state",
        envvar=["DBT_STATE"],
        default=None,
        type=str,
        callback=make_config_callback("DBT_STATE"),
        help="Path to the reference manifest.json directory (local path where state will be downloaded)",
    ),
    click.option(
        "--target", "-t",
        envvar=["DBT_TARGET"],
        default=None,
        callback=make_config_callback("DBT_TARGET"),
        help="The dbt target to use (defaults to what is defined in profiles.yml)",
    ),
    click.option(
        "--vars", "-v",
        envvar=["DBT_VARS"],
        default="",
        callback=make_config_callback("DBT_VARS"),
        help="A YAML string or path to YAML file containing variables to pass to dbt",
    ),
    click.option(
        "--defer",
        envvar=["DBT_DEFER"],
        is_flag=True,
        default=False,
        callback=make_defer_callback(),
        help=(
            "Use dbt's --defer flag to defer to the state of the production manifest (only applicable to run and test commands). "
            "Also read from DEFER_FLAG ('--defer', empty or a boolean) when DBT_DEFER is not set"
        ),
    ),
    click.option(
        "--runner", "-r",
        envvar=["DBT_RUNNER"],
        type=click.Choice(["local", "docker", "bash", "dbt"]),
        default="dbt",
        callback=make_config_callback("DBT_RUNNER"),
        help="Runner to use for executing dbt commands",
    ),
    click.option(
        "--entrypoint",
        envvar=["DBT_ENTRYPOINT"],
        default="dbt",
        callback=make_config_callback("DBT_ENTRYPOINT"),
        help="Command entrypoint for dbt (default: dbt)",
    ),
    click.option(
        "--dry-run",
        envvar=["DBT_DRY_RUN"],
        is_flag=True,
        default=False,
        callback=make_config_callback("DBT_DRY_RUN"),
        help="Print commands without executing them",
    ),
    click.option(
        "--log-level",
        envvar=["DBT_LOG_LEVEL"],
        # WARN and NONE are dbt's spellings, accepted because both tools read DBT_LOG_LEVEL
        type=click.Choice(["DEBUG", "INFO", "WARNING", "WARN", "ERROR", "CRITICAL", "NONE"], case_sensitive=False),
        default="INFO",
        callback=make_config_callback("DBT_LOG_LEVEL", then=normalise_log_level),
        help="Logging level",
    ),
    click.option(
        "--slack-webhook",
        "--slack-webhook-url",
        envvar=["SLACK_WEBHOOK", "SLACK_WEBHOOK_URL"],
        default=None,
        type=str,
        callback=make_config_callback("SLACK_WEBHOOK"),
        help="Slack webhook URL for notifications (optional)",
    ),
    click.option(
        "--slack-format",
        envvar=["SLACK_FORMAT"],
        type=click.Choice(["default", "compact", "json"], case_sensitive=False),
        default="default",
        callback=make_config_callback("SLACK_FORMAT"),
        help=(
            "Layout of the Slack summary: 'default' lists changed nodes by name, "
            "'compact' sends only the counts, 'json' sends the unique_ids as a JSON code block"
        ),
    ),
    click.option(
        "--docker-image",
        envvar=["DBT_DOCKER_IMAGE"],
        default="ghcr.io/dbt-labs/dbt-core:latest",
        callback=make_config_callback("DBT_DOCKER_IMAGE"),
        help="Docker image to use",
    ),
    click.option(
        "--docker-platform",
        envvar=["DBT_DOCKER_PLATFORM"],
        default=None,
        callback=make_config_callback("DBT_DOCKER_PLATFORM"),
        help="Platform for Docker (e.g., linux/amd64)",
    ),
    click.option(
        "--docker-volumes",
        envvar=["DBT_DOCKER_VOLUMES"],
        multiple=True,
        type=NEWLINE_SEPARATED,
        callback=make_config_callback("DBT_DOCKER_VOLUMES", then=parse_multiple_option),
        help=(
            "Additional volume mounts (format: host:container). Repeat flag for multiple "
            "volumes: --docker-volumes /path1:/path1 --docker-volumes /path2:/path2. "
            'Via env var, use comma or newline separation: DBT_DOCKER_VOLUMES="/p1:/p1,/p2:/p2"'
        ),
    ),
    click.option(
        "--docker-env",
        envvar=["DBT_DOCKER_ENV"],
        multiple=True,
        type=NEWLINE_SEPARATED,
        callback=make_config_callback("DBT_DOCKER_ENV", then=parse_env_option),
        help=(
            "Environment variables (format: KEY=VALUE). Repeat flag for multiple vars: "
            "--docker-env VAR1=val1 --docker-env VAR2=val2. Via env var, use comma or "
            'newline separation: DBT_DOCKER_ENV="KEY1=val1,KEY2=val2"'
        ),
    ),
    click.option(
        "--docker-network",
        envvar=["DBT_DOCKER_NETWORK"],
        default="host",
        callback=make_config_callback("DBT_DOCKER_NETWORK"),
        help="Docker network mode",
    ),
    click.option(
        "--docker-user",
        envvar=["DBT_DOCKER_USER"],
        default=None,
        callback=make_config_callback("DBT_DOCKER_USER"),
        help="User to run as inside container",
    ),
    click.option(
        "--docker-args",
        envvar=["DBT_DOCKER_ARGS"],
        default="",
        callback=make_config_callback("DBT_DOCKER_ARGS"),
        help="Additional docker run arguments",
    ),
    click.option(
        "--shell-path",
        "--bash-path",
        envvar=["DBT_SHELL_PATH"],
        default="/bin/bash",
        callback=make_config_callback("DBT_SHELL_PATH"),
        help="Path to shell executable for bash runner",
    ),
    click.option(
        "--quiet", "-q",
        envvar=["DBT_QUIET"],
        is_flag=True,
        default=False,
        callback=make_config_callback("DBT_QUIET"),
        help="Run in quiet mode with minimal output",
    ),
]


def common_options(func):
    """Add common dbt-ci options to a Click command."""
    for option in COMMON_OPTIONS:
        func = option(func)
    return func