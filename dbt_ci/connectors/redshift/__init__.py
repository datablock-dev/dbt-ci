"""Native Redshift connector."""
from dbt_ci.schema import ConnectorConfig
from dbt_ci.connectors.dbapi import build_delete_strategy, build_migration_strategy
from dbt_ci.connectors.redshift.client import redshift_connector, redshift_client
from dbt_ci.connectors.redshift.migration import plan_redshift_migration

redshift_db_connector: ConnectorConfig = {
    "client": redshift_client,
    "strategies": {
        "delete": build_delete_strategy(redshift_client),
        "migration": build_migration_strategy(redshift_client, plan_redshift_migration)
    }
}


def is_available() -> bool:
    """Report whether redshift-connector is installed, so the registry can fall back if not."""
    return redshift_connector is not None

__all__ = [
    "is_available",
    "plan_redshift_migration",
    "redshift_client",
    "redshift_db_connector",
]
