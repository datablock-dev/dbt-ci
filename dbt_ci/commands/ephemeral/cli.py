import click
from dbt_ci.utilities.cache import CacheManager
from dbt_ci.main import cli
from dbt_ci.cli.common_options import common_options
from dbt_ci.utilities.logging import setup_logging
from dbt_ci.cli.namespace import to_namespace
from dbt_ci.commands.ephemeral.index import ephemeral
from dbt_ci.commands.ephemeral.destroy import destroy

keep_env_option = click.option(
    "--keep-env",
    envvar=['DBT_KEEP_ENV'],
    is_flag=True,
    default=False,
    hidden=True,
    help=(
        "DEPRECATED - has no effect. Creating the environment never destroys it; "
        "use 'dbt-ci ephemeral destroy' to tear it down."
    )
)


def run_create(kwargs: dict) -> None:
    """Create the ephemeral environment from the given CLI options."""
    setup_logging(to_namespace(kwargs).log_level)
    args = to_namespace(kwargs, command="ephemeral")
    with CacheManager(args).track_report("ephemeral"):
        ephemeral(args)


@cli.group(name='ephemeral', invoke_without_command=True)
@common_options
@keep_env_option
@click.pass_context
def ephemeral_cmd(ctx: click.Context, **kwargs):
    """Create or destroy the ephemeral CI environment

    Without a subcommand this creates the environment, as 'ephemeral create' does.

    Examples:
        # Run after init
        dbt-ci init --state-uri gs://bucket/manifest.json --reference-target production
        dbt-ci ephemeral create --runner docker
        dbt-ci ephemeral destroy
    """
    if ctx.invoked_subcommand is None:
        return run_create(kwargs)

    # Options belong to the subcommand; ones given before it would otherwise be dropped.
    misplaced = [
        param.opts[0] for param in ctx.command.params
        if ctx.get_parameter_source(param.name) == click.core.ParameterSource.COMMANDLINE
    ]
    if misplaced:
        raise click.UsageError(
            f"Pass {', '.join(misplaced)} after the subcommand, "
            f"e.g. 'dbt-ci ephemeral {ctx.invoked_subcommand} {misplaced[0]} ...'."
        )


@ephemeral_cmd.command(name='create')
@common_options
@keep_env_option
def ephemeral_create_cmd(**kwargs):
    """Clone the changed nodes and their dependencies into the CI target

    Uses cached state from 'dbt-ci init' to create the ephemeral environment, and records
    the datasets it cloned into so 'dbt-ci ephemeral destroy' can drop them later.

    Examples:
        dbt-ci ephemeral create --target ci
        dbt-ci ephemeral --target ci   # same thing
    """
    run_create(kwargs)


@ephemeral_cmd.command(name='destroy')
@common_options
def ephemeral_destroy_cmd(**kwargs):
    """Drop the datasets 'dbt-ci ephemeral' cloned into

    Datasets used by any node in the reference (production) manifest are never dropped.
    Run it in the same job as 'ephemeral', since it reads the list of cloned datasets
    from the dbt-ci cache. The cache is left in place, so a failed teardown can be retried.

    Examples:
        dbt-ci ephemeral destroy
        dbt-ci ephemeral destroy --dry-run   # list what would be dropped
    """
    setup_logging(to_namespace(kwargs).log_level)
    destroy(to_namespace(kwargs, command="ephemeral"))
