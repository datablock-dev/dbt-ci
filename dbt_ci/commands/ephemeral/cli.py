import click
from dbt_ci.main import cli
from dbt_ci.cli.common_options import common_options
from dbt_ci.utilities.logging import setup_logging
from dbt_ci.cli.namespace import to_namespace
from dbt_ci.commands.ephemeral.index import ephemeral

@cli.command(name='ephemeral')
@common_options
@click.option(
    "--keep-env",
    envvar=['DBT_KEEP_ENV'],
    is_flag=True,
    default=False,
    help=(
        "DEPRECATED - has no effect. The ephemeral command never destroys the environment "
        "it creates; use 'dbt-ci finalize --clean-ephemeral' to tear it down."
    )
)
def ephemeral_cmd(**kwargs):
    """Run ephemeral CI check workflow

    Uses cached state from 'dbt-ci init' to create and test ephemeral schemas.
    Useful for full integration testing in isolated environments.

    Examples:
        # Run after init
        dbt-ci init --state-uri gs://bucket/manifest.json --reference-target production
        dbt-ci ephemeral --runner docker
    """
    setup_logging(to_namespace(kwargs).log_level)
    return ephemeral(to_namespace(kwargs, command="ephemeral"))