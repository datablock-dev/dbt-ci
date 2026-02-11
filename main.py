from argparse import Namespace
import click
from src.commands import (
    delete,
    run,
    ephemeral,
    init
)
from src.logging import setup_logging

# Shared options for all commands
def common_options(f):
    """Decorator to add common options to all commands"""
    f = click.option(
        '--prod-manifest-dir', 
        '--reference-manifest-dir', 
        '--state',
        help='Path to the production/reference manifest.json directory'
    )(f)
    f = click.option(
        '--dbt-project-dir', 
        default='.',
        help='Path to the dbt project directory (default: current directory)'
    )(f)
    f = click.option(
        '--profiles-dir', 
        default=None,
        help='Path to the directory containing the dbt profiles.yml file'
    )(f)
    f = click.option(
        '--production-target',
        default=None,
        help='The dbt target to use for production/reference manifest (defaults to default)'
    )(f)
    f = click.option(
        '--target', 
        '-t', 
        default=None,
        help='The dbt target to use (defaults to what is defined in profiles.yml)'
    )(f)
    f = click.option(
        '--vars', 
        '-v', 
        default='',
        help='A YAML string or path to YAML file containing variables to pass to dbt'
    )(f)
    f = click.option(
        '--runner', 
        '-r', 
        type=click.Choice(['local', 'docker', 'bash', 'dbt']),
        default='dbt',
        help='Runner to use for executing dbt commands'
    )(f)
    f = click.option(
        '--entrypoint', 
        default='dbt',
        help='Command entrypoint for dbt (default: dbt)'
    )(f)
    f = click.option(
        '--dry-run', 
        is_flag=True,
        default=False,
        help='Print commands without executing them'
    )(f)
    f = click.option(
        '--log-level', 
        type=click.Choice(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']),
        default='INFO',
        help='Logging level'
    )(f)
    f = click.option(
        "--slack-webhook",
        "--slack-webhook-url",
        default=None,
        type=str,
        help="Slack webhook URL for notifications (optional)"
    )(f)
    
    # Docker options
    f = click.option(
        '--docker-image', 
        default='ghcr.io/dbt-labs/dbt-core:latest',
        help='Docker image to use'
    )(f)
    f = click.option(
        '--docker-platform', 
        default=None,
        help='Platform for Docker (e.g., linux/amd64)'
    )(f)
    f = click.option(
        '--docker-volumes', 
        multiple=True,
        help='Additional volume mounts (format: host:container). Repeat flag for multiple volumes: --docker-volumes /path1:/path1 --docker-volumes /path2:/path2'
    )(f)
    f = click.option(
        '--docker-env', 
        multiple=True,
        help='Environment variables (format: KEY=VALUE). Repeat flag for multiple vars: --docker-env VAR1=val1 --docker-env VAR2=val2'
    )(f)
    f = click.option(
        '--docker-network', 
        default='host',
        help='Docker network mode'
    )(f)
    f = click.option(
        '--docker-user', 
        default=None,
        help='User to run as inside container'
    )(f)
    f = click.option(
        '--docker-args', 
        default='',
        help='Additional docker run arguments'
    )(f)
    # Bash options
    f = click.option(
        '--shell-path', 
        '--bash-path', 
        default='/bin/bash',
        help='Path to shell executable for bash runner'
    )(f)

    return f


@click.group()
@click.version_option(version='0.1.0', prog_name='dbt-ci')
def cli():
    """dbt CI Tool - Intelligent CI for dbt projects
    
    Detect, run, and test only what changed based on state comparison.
    
    Visit https://datablock.dev for more information.
    """
    pass

@cli.command(name="init")
@common_options
def init_cmd(**kwargs):
    """Initialize dbt CI state
    
    Creates initial state from production manifest. Run this before using other commands.
    
    Examples:
        dbt-ci init --prod-manifest-dir prod-manifest/ --dbt-project-dir ./dbt --production-target production
    """
    setup_logging(to_namespace(kwargs).log_level)
    return init(**kwargs)

# Add support for --levels option to specify how many levels of dependencies to include
@cli.command(name='run')
@common_options
@click.option(
    '--nodes', '-n',
    type=click.Choice([
        "all",
        "models",
        "seeds",
        "snapshots",
        "tests",
        #"analyses" --> Not yet supported
    ], case_sensitive=False),
    default='all',
    help='Run mode for dbt-ci (default: auto)'
)
@click.option(
    "--levels",
    type=int,
    default=None,
    help="Number of dependency levels to include (default: all)"
)
def run_cmd(**kwargs):
    """Run modified dbt models
    
    Detects models that have changed based on state comparison and runs them.
    
    Examples:
        dbt-ci run --state prod-manifest/ --dbt-project-dir ./dbt
        dbt-ci run --state prod-manifest/ --runner docker
        
        # With environment variables
        export DBT_STATE=./dbt/.dbtstate/
        export DBT_PROJECT_DIR=./dbt
        dbt-ci run
    """
    setup_logging(to_namespace(kwargs).log_level)
    return run(**kwargs)


@cli.command(name='ephemeral')
@common_options
@click.option(
    "--keep-env",
    is_flag=True,
    default=False,
    help="Don't destroy ephemeral environment after run (if supported by runner)"
)
def ephemeral_cmd(**kwargs):
    """Run ephemeral CI check workflow
    
    Detects changes, lists modified models, but doesn't execute them.
    Useful for quick CI checks and PR previews.
    
    Examples:
        dbt-ci ephemeral --state prod-manifest/ --dbt-project-dir ./dbt
        dbt-ci ephemeral --state prod-manifest/ --runner docker
        
        # With environment variables
        export DBT_STATE=./dbt/.dbtstate/
        export DBT_PROJECT_DIR=./dbt
        dbt-ci ephemeral
    """
    setup_logging(to_namespace(kwargs).log_level)
    return ephemeral(**kwargs)

@cli.command(name='delete')
@common_options
def delete_cmd(**kwargs):
    """Delete modified dbt models
    
    Detects models that have been deleted based on state comparison and deletes them from the target environment.
    
    Examples:
        dbt-ci delete --state prod-manifest/ --dbt-project-dir ./dbt
        dbt-ci delete --state prod-manifest/ --runner docker
        
        # With environment variables
        export DBT_STATE=./dbt/.dbtstate/
        export DBT_PROJECT_DIR=./dbt
        dbt-ci delete
    """
    setup_logging(to_namespace(kwargs).log_level)
    return delete(**kwargs)

def to_namespace(kwargs):
    """Convert kwargs dict to argparse.Namespace for easier access and compatibility with existing code"""
    return Namespace(**kwargs)

if __name__ == "__main__":
    cli()
