from dbt_ci.main import cli
from dbt_ci.utilities.cache import CacheManager
from dbt_ci.cli.common_options import common_options
from dbt_ci.cli.namespace import to_namespace
from dbt_ci.utilities.logging import setup_logging
from dbt_ci.commands.migration.index import migration


@cli.command(name="migration")
@common_options
def migration_cmd(**kwargs):
    """Move incremental tables onto a changed layout

    Uses cached state from 'dbt-ci init' to find incremental models whose partitioning,
    clustering, sort or distribution keys changed, and changes their tables to match,
    keeping their rows (BigQuery, Snowflake, Redshift and Databricks).

    \b
    Examples:
        # Run after init
        dbt-ci init --state-uri gs://bucket/manifest.json --reference-target production
        dbt-ci migration --dry-run   # show the tables and statements first
        dbt-ci migration
    """
    setup_logging(to_namespace(kwargs).log_level)
    args = to_namespace(kwargs, command="migration")
    with CacheManager(args).track_report("migrate"):
        return migration(args)
