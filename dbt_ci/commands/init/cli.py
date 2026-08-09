import click
from dbt_ci.main import cli
from dbt_ci.cli.common_options import common_options
from dbt_ci.cli.config import make_config_callback
from dbt_ci.cli.namespace import to_namespace
from dbt_ci.utilities.logging import setup_logging
from dbt_ci.commands.init.index import init

@cli.command(name="init")
@common_options
@click.option(
    "--reference-target", "--ref-target",
    envvar=['DBT_REFERENCE_TARGET'],
    default=None,
    callback=make_config_callback("DBT_INIT_REFERENCE_TARGET"),
    help="The dbt target to use for production/reference manifest (defaults to default)"
)
@click.option(
    "--reference-vars", "--ref-vars",
    envvar=['DBT_REFERENCE_VARS'],
    default=None,
    callback=make_config_callback("DBT_INIT_REFERENCE_VARS"),
    help="Variables to pass to dbt when compiling the reference manifest (YAML string or path to YAML file)"
)
@click.option(
    "--state-uri",
    envvar=['DBT_STATE_URI', 'STATE_URI'],
    default=None,
    callback=make_config_callback("DBT_INIT_STATE_URI"),
    help="Remote URI for the state manifest.json file (e.g., gs://my-bucket/dbt-state/manifest.json or s3://my-bucket/dbt-state/manifest.json)"
)
@click.option(
    "--reference-path",
    envvar=["DBT_REFERENCE_PATH"],
    default="reference",
    callback=make_config_callback("DBT_INIT_REFERENCE_PATH"),
    help=(
        "DEPRECATED - has no effect. The reference compile writes to dbt's own target "
        "path; this option is never passed to dbt."
    )
)
@click.option(
    "--target-compile",
    envvar=['DBT_TARGET_COMPILE'],
    is_flag=True,
    default=False,
    callback=make_config_callback("DBT_INIT_TARGET_COMPILE"),
    help="Compile towards target (or default)"
)
@click.option(
    "--skip-reference-compile",
    envvar=['DBT_SKIP_REFERENCE_COMPILE'],
    is_flag=True,
    default=False,
    callback=make_config_callback("DBT_INIT_SKIP_REFERENCE_COMPILE"),
    help="Skip compiling towards reference (production) state"
)
@click.option(
    "--comparison-strategy", "--comparison",
    envvar=['DBT_COMPARISON_STRATEGY'],
    default="hybrid",
    type=click.Choice(["dbt", "git", "hybrid"], case_sensitive=False),
    multiple=False,
    callback=make_config_callback("DBT_INIT_COMPARISON_STRATEGY"),
    help="Strategy to use for state comparison (default: hybrid). Available options: dbt, git, hybrid"
)
@click.option(
    "--base-ref",
    envvar=['DBT_CI_BASE_REF'],
    default=None,
    callback=make_config_callback("DBT_INIT_BASE_REF"),
    help="The base branch to diff against (e.g. main). Auto-detected from git/CI env if not set."
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