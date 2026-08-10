"""Native Snowflake connector."""
from dbt_ci.schema import ConnectorConfig
from dbt_ci.connectors.dbapi import build_delete_strategy, build_migration_strategy
from dbt_ci.connectors.snowflake.client import snowflake_connector, snowflake_client
from dbt_ci.connectors.snowflake.migration import plan_snowflake_migration

snowflake_db_connector: ConnectorConfig = {
    "client": snowflake_client,
    "strategies": {
        "delete": build_delete_strategy(snowflake_client),
        "migration": build_migration_strategy(snowflake_client, plan_snowflake_migration)
    }
}


def is_available() -> bool:
    """Report whether snowflake-connector-python is installed, so the registry can fall back if not."""
    return snowflake_connector is not None

__all__ = [
    "is_available",
    "plan_snowflake_migration",
    "snowflake_client",
    "snowflake_db_connector",
]
