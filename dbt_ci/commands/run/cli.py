import click
from dbt_ci.main import cli
from dbt_ci.cli.common_options import common_options
from dbt_ci.cli.namespace import to_namespace
from dbt_ci.logging import setup_logging
from dbt_ci.commands.run.index import run

@cli.command(name='run')
@common_options
@click.option(
    '--nodes', '-n',
    '--mode', '-m',
    envvar=['DBT_NODES'],
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
    help="Extra filters to apply for tests, dbt-lineage run -m tests -f snapshots to run tests that has a snapshot dependency"
)
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
    return run(to_namespace(kwargs, command="run"))