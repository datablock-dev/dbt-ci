from dbt_ci.main import common_options, cli
from dbt_ci.utilities.namespace import to_namespace
from dbt_ci.logging import setup_logging
from dbt_ci.commands.delete.index import delete

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
    return delete(to_namespace(kwargs, command="delete"))