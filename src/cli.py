# Shared options for all commands
import click

def parse_multiple_option(ctx, param, value):
    """
    Parse multiple values that may arrive as a single string when set via env var.
    When a single string is received (e.g. from env var), splits on commas or newlines.
    When multiple values are already provided (e.g. from repeated CLI flags), passes through unchanged.

    Examples:
        DBT_DOCKER_ENV="KEY1=val1,KEY2=val2"   -> ('KEY1=val1', 'KEY2=val2')
        --docker-env KEY1=val1 --docker-env KEY2=val2  -> ('KEY1=val1', 'KEY2=val2') (unchanged)
    """
    if not value:
        return value
    if len(value) == 1 and (',' in value[0] or '\n' in value[0]):
        return tuple(p.strip() for p in value[0].replace('\n', ',').split(',') if p.strip())
    return value


def common_options(f):
    """Decorator to add common options to all commands"""
    # Dynamic package options
    f = click.option(
        "--dbt-version",
        envvar=['DBT_VERSION'],
        default=None,
        help="Specify a dbt version to use for this command"
    )(f)
    f = click.option(
        "--adapter", "-a",
        envvar=['DBT_ADAPTER'],
        type=str,
        default=None,
        help="Specify the dbt adapter to use (e.g., 'postgres', 'snowflake')"
    )(f)
    # Main commands
    f = click.option(
        '--dbt-project-dir', 
        envvar=['DBT_PROJECT_DIR'],
        default='.',
        help='Path to the dbt project directory (default: current directory)'
    )(f)
    f = click.option(
        '--profiles-dir', 
        envvar=['DBT_PROFILES_DIR'],
        default=None,
        help='Path to the directory containing the dbt profiles.yml file'
    )(f)
    f = click.option(
        '--target', 
        '-t',
        envvar=['DBT_TARGET'],
        default=None,
        help='The dbt target to use (defaults to what is defined in profiles.yml)'
    )(f)
    f = click.option(
        '--vars', 
        '-v',
        envvar=['DBT_VARS'],
        default='',
        help='A YAML string or path to YAML file containing variables to pass to dbt'
    )(f)
    f = click.option(
        "--defer",
        envvar=['DBT_DEFER'],
        is_flag=True,
        default=False,
        help="Use dbt's --defer flag to defer to the state of the production manifest (only applicable to run and test commands)"
    )(f)
    f = click.option(
        '--runner', 
        '-r', 
        envvar=['DBT_RUNNER'],
        type=click.Choice(['local', 'docker', 'bash', 'dbt']),
        default='dbt',
        help='Runner to use for executing dbt commands'
    )(f)
    f = click.option(
        '--entrypoint',
        envvar=['DBT_ENTRYPOINT'],
        default='dbt',
        help='Command entrypoint for dbt (default: dbt)'
    )(f)
    f = click.option(
        '--dry-run',
        envvar=['DBT_DRY_RUN'],
        is_flag=True,
        default=False,
        help='Print commands without executing them'
    )(f)
    f = click.option(
        '--log-level',
        envvar=['DBT_LOG_LEVEL'],
        type=click.Choice(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], case_sensitive=False),
        default='INFO',
        callback=lambda ctx, param, value: value.upper() if value else value,
        help='Logging level'
    )(f)
    f = click.option(
        "--slack-webhook",
        "--slack-webhook-url",
        envvar=['SLACK_WEBHOOK', 'SLACK_WEBHOOK_URL'],
        default=None,
        type=str,
        help="Slack webhook URL for notifications (optional)"
    )(f)
    # Docker options
    f = click.option(
        '--docker-image',
        envvar=['DBT_DOCKER_IMAGE'],
        default='ghcr.io/dbt-labs/dbt-core:latest',
        help='Docker image to use'
    )(f)
    f = click.option(
        '--docker-platform',
        envvar=['DBT_DOCKER_PLATFORM'],
        default=None,
        help='Platform for Docker (e.g., linux/amd64)'
    )(f)
    f = click.option(
        '--docker-volumes',
        envvar=['DBT_DOCKER_VOLUMES'],
        multiple=True,
        callback=parse_multiple_option,
        help='Additional volume mounts (format: host:container). Repeat flag for multiple volumes: --docker-volumes /path1:/path1 --docker-volumes /path2:/path2. Via env var, use comma or newline separation: DBT_DOCKER_VOLUMES="/p1:/p1,/p2:/p2"'
    )(f)
    f = click.option(
        '--docker-env',
        envvar=['DBT_DOCKER_ENV'],
        multiple=True,
        callback=parse_multiple_option,
        help='Environment variables (format: KEY=VALUE). Repeat flag for multiple vars: --docker-env VAR1=val1 --docker-env VAR2=val2. Via env var, use comma or newline separation: DBT_DOCKER_ENV="KEY1=val1,KEY2=val2"'
    )(f)
    f = click.option(
        '--docker-network',
        envvar=['DBT_DOCKER_NETWORK'],
        default='host',
        help='Docker network mode'
    )(f)
    f = click.option(
        '--docker-user',
        envvar=['DBT_DOCKER_USER'],
        default=None,
        help='User to run as inside container'
    )(f)
    f = click.option(
        '--docker-args',
        envvar=['DBT_DOCKER_ARGS'],
        default='',
        help='Additional docker run arguments'
    )(f)
    # Bash options
    f = click.option(
        '--shell-path', 
        '--bash-path',
        envvar=['DBT_SHELL_PATH', 'SHELL_PATH'],
        default='/bin/bash',
        help='Path to shell executable for bash runner'
    )(f)

    return f
