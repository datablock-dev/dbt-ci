"""DBT CI Tool - Intelligent CI for DBT projects"""
from argparse import Namespace
import click
from src.cli import common_options
from src.logging import setup_logging
from src.commands import (
    delete,
    run,
    ephemeral,
    init,
    finalize
)

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
@click.option(
    '--reference-state', '--state',
    default=None,
    type=str,
    help='Path to the reference manifest.json directory (local path where state will be downloaded)'
)
@click.option(
    "--state-uri",
    envvar=['DBT_STATE_URI', 'STATE_URI'],
    default=None,
    help="Remote URI for the state manifest.json file (e.g., gs://my-bucket/dbt-state/manifest.json or s3://my-bucket/dbt-state/manifest.json)"
)
def init_cmd(**kwargs):
    """Initialize dbt CI state
    
    Downloads reference manifest and compares with current state. Creates cache for subsequent commands.
    Run this before using run, delete, or ephemeral commands.
    
    Examples:
        # Download from GCS and use sandbox target as reference
        dbt-ci init --state-uri gs://bucket/manifest.json --reference-target sandbox --state dbt/.dbtstate
        
        # Use local state directory
        dbt-ci init --state dbt/.dbtstate --reference-target production
    """
    print(to_namespace(kwargs))
    setup_logging(to_namespace(kwargs).log_level)
    return init(to_namespace(kwargs))

# Add support for --levels option to specify how many levels of dependencies to include
@cli.command(name='run')
@common_options
@click.option(
    '--nodes', '-n',
    '--mode', '-m',
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
    '--filters', '-f',
    type=click.Choice([
        'models', 
        'seeds', 
        'snapshots', 
        'tests'
    ], case_sensitive=False),
    multiple=True,
    default=None,
    help="Extra filters to apply for tests, dbt-lineage run -m tests -f snapshots to run modified models and their snapshot dependencies only"
)
#@click.option( # Not yet implemented
#    "--levels",
#    type=int,
#    default=None,
#    help="Number of dependency levels to include (default: all)"
#)
def run_cmd(**kwargs):
    """Run modified dbt models
    
    Uses cached state from 'dbt-ci init' to detect and run modified models.
    
    Examples:
        # Run after init
        dbt-ci init --state-uri gs://bucket/manifest.json --reference-target production
        dbt-ci run --runner docker
        
        # Simple local run
        dbt-ci run
    """
    setup_logging(to_namespace(kwargs).log_level)
    return run(to_namespace(kwargs))


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
    
    Uses cached state from 'dbt-ci init' to create and test ephemeral schemas.
    Useful for full integration testing in isolated environments.
    
    Examples:
        # Run after init
        dbt-ci init --state-uri gs://bucket/manifest.json --reference-target production
        dbt-ci ephemeral --runner docker
        
        # Keep environment for debugging
        dbt-ci ephemeral --keep-env
    """
    setup_logging(to_namespace(kwargs).log_level)
    return ephemeral(to_namespace(kwargs))

@cli.command(name='delete')
@common_options
def delete_cmd(**kwargs):
    """Delete removed dbt models
    
    Uses cached state from 'dbt-ci init' to detect and delete models removed from the project.
    
    Examples:
        # Run after init
        dbt-ci init --state-uri gs://bucket/manifest.json --reference-target production
        dbt-ci delete --runner docker
        
        # Dry run to preview deletions
        dbt-ci delete --dry-run
    """
    setup_logging(to_namespace(kwargs).log_level)
    return delete(to_namespace(kwargs))

@cli.command(name="finalize")
@common_options
@click.option(
    "--artifacts-uri",
    default=None,
    envvar=['ARTIFACTS_URI'],
    type=str,
    help="S3/Object storage URI for storing artifacts like updated manifest.json files (e.g., s3://my-bucket/dbt-artifacts/)"
)
def finalize_cmd(**kwargs):
    """Finalize the state after running CI commands
    
    This command should be run after 'run' or 'delete' to update the reference state with the new production state.
    It will also clean up any temporary files and reset the cache for the next run.
    
    Examples:
        dbt-ci finalize
        dbt-ci finalize --artifacts-uri s3://my-bucket/dbt-artifacts/
    """
    setup_logging(to_namespace(kwargs).log_level)
    return finalize(to_namespace(kwargs))
    

def to_namespace(kwargs):
    """Convert kwargs dict to argparse.Namespace for easier access and compatibility with existing code"""
    return Namespace(**kwargs)

if __name__ == "__main__":
    cli()
