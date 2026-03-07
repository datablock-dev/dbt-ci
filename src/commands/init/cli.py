import click
from src.cli import common_options, cli
from src.utilities.namespace import to_namespace
from src.logging import setup_logging
from src.commands.init.index import init

@cli.command(name="init")
@common_options
@click.option(
    "--reference-target", "-ref-target",
    envvar=['DBT_REFERENCE_TARGET'],
    default=None,
    help="The dbt target to use for production/reference manifest (defaults to default)"
)
@click.option(
    '--reference-state', '--state',
    envvar=['DBT_STATE', 'DBT_STATE_DIR', 'STATE_DIR'],
    default=None,
    type=str,
    help='Path to the reference manifest.json directory (local path where state will be downloaded)'
)
@click.option(
    "--reference-vars", "--ref-vars",
    envvar=['DBT_REFERENCE_VARS'],
    default=None,
    help="Variables to pass to dbt when compiling the reference manifest (YAML string or path to YAML file)"
)
@click.option(
    "--state-uri",
    envvar=['DBT_STATE_URI', 'STATE_URI'],
    default=None,
    help="Remote URI for the state manifest.json file (e.g., gs://my-bucket/dbt-state/manifest.json or s3://my-bucket/dbt-state/manifest.json)"
)
@click.option(
    "--skip-target-compile",
    envvar=['DBT_SKIP_TARGET_COMPILE'],
    is_flag=True,
    default=False,
    help="Skip compiling towards target (or default)"
)
@click.option(
    "--skip-reference-compile",
    envvar=['DBT_SKIP_REFERENCE_COMPILE'],
    is_flag=True,
    default=False,
    help="Skip compiling towards reference (production) state"
)
@click.option(
    "--no-git",
    envvar=['DBT_NO_GIT'],
    is_flag=True,
    default=False,
    help="Whether to skip git comparison"
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
    setup_logging(to_namespace(kwargs).log_level)
    return init(to_namespace(kwargs, command="init"))