from dbt_ci.cli import common_options, cli
from dbt_ci.utilities.namespace import to_namespace
from dbt_ci.logging import setup_logging
from dbt_ci.commands.migration.index import migration

@cli.command(name="migration")
@common_options
def migration_cmd(**kwargs):
    """Run migration check workflow
    
    Uses cached state from 'dbt-ci init' to detect breaking changes and run migration checks.
    Useful for validating changes before merging to production.
    
    Examples:
        # Run after init
        dbt-ci init --state-uri gs://bucket/manifest.json --reference-target production
        dbt-ci migration --runner docker
    """
    setup_logging(to_namespace(kwargs).log_level)
    return migration(to_namespace(kwargs, command="migration"))