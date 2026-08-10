"""Native Databricks connector."""
from dbt_ci.schema import ConnectorConfig
from dbt_ci.connectors.dbapi import build_delete_strategy, build_migration_strategy
from dbt_ci.connectors.databricks.client import databricks_sql, databricks_client
from dbt_ci.connectors.databricks.migration import plan_databricks_migration

databricks_db_connector: ConnectorConfig = {
    "client": databricks_client,
    "strategies": {
        "delete": build_delete_strategy(databricks_client),
        "migration": build_migration_strategy(databricks_client, plan_databricks_migration)
    }
}


def is_available() -> bool:
    """Report whether databricks-sql-connector is installed, so the registry can fall back if not."""
    return databricks_sql is not None

__all__ = [
    "is_available",
    "databricks_client",
    "databricks_db_connector",
    "plan_databricks_migration",
]
