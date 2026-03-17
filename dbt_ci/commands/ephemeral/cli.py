import click
from dbt_ci.main import cli
from dbt_ci.cli.common_options import common_options
from dbt_ci.logging import setup_logging
from dbt_ci.cli.namespace import to_namespace
from dbt_ci.commands.ephemeral.index import ephemeral

@cli.command(name='ephemeral')
@common_options
@click.option(
    "--keep-env",
    envvar=['DBT_KEEP_ENV'],
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
    return ephemeral(to_namespace(kwargs, command="ephemeral"))