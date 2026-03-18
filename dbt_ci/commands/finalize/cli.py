import click
from dbt_ci.main import cli
from dbt_ci.cli.namespace import to_namespace
from dbt_ci.cli.config import make_config_callback
from dbt_ci.utilities.logging import setup_logging
from dbt_ci.commands.finalize.index import finalize
from dbt_ci.cli.common_options import common_options, parse_multiple_option

valid_files = {"manifest", "cache", "log"}

def parse_and_validate_files(value):
    value = parse_multiple_option(value)
    for file in value:
        if file not in valid_files:
            raise click.BadParameter(f"Invalid file specified: {file}. Valid options are: {', '.join(valid_files)}")
    return value

@cli.command(name="finalize")
@common_options
@click.option(
    "--artifacts-uri",
    envvar=['DBT_ARTIFACTS_URI', 'ARTIFACTS_URI'],
    default=None,
    type=str,
    help="S3/Object storage URI for storing artifacts like updated manifest.json files (e.g., s3://my-bucket/dbt-artifacts/)"
)
@click.option(
    "--files",
    envvar=["DBT_FINALIZE_FILES"],
    default=["manifest"],
    multiple=True,
    callback=make_config_callback("DBT_FINALIZE_FILES", then=parse_and_validate_files),
    help=f"Specify which files to upload during finalize (default: manifest). Valid options: {', '.join(valid_files)}"
)
@click.option(
    "--clean-ephemeral",
    "--destroy-ephemeral",
    envvar=['DBT_CLEAN_EPHEMERAL', "DBT_DESTROY_EPHEMERAL"],
    is_flag=True,
    default=False,
    help="Whether to clean up ephemeral environment after finalizing"
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
    return finalize(to_namespace(kwargs, command="finalize"))