"""Native connectors for the Azure SQL family: SQL Server, Synapse and Fabric."""
from dbt_ci.schema import ConnectorConfig
from dbt_ci.connectors.dbapi import build_delete_strategy, build_migration_strategy
from dbt_ci.connectors.dbapi.strategies import build_noop_migration_strategy
from dbt_ci.connectors.azure.client import pyodbc, azure_client
from dbt_ci.connectors.azure.migration import plan_synapse_migration

synapse_db_connector: ConnectorConfig = {
    "client": azure_client,
    "strategies": {
        "delete": build_delete_strategy(azure_client),
        "migration": build_migration_strategy(azure_client, plan_synapse_migration)
    }
}

sqlserver_db_connector: ConnectorConfig = {
    "client": azure_client,
    "strategies": {
        "delete": build_delete_strategy(azure_client),
        "migration": build_noop_migration_strategy(
            "Azure SQL Database has no distribution configuration to migrate; index changes "
            "are applied by dbt on a rebuild."
        )
    }
}

fabric_db_connector: ConnectorConfig = {
    "client": azure_client,
    "strategies": {
        "delete": build_delete_strategy(azure_client),
        "migration": build_noop_migration_strategy(
            "Fabric Warehouse cannot rename a table, so a layout change has to be applied "
            "by rebuilding the model with 'dbt run --full-refresh'."
        )
    }
}


def is_available() -> bool:
    """Report whether pyodbc is installed, so the registry can fall back if not."""
    return pyodbc is not None

__all__ = [
    "is_available",
    "azure_client",
    "fabric_db_connector",
    "plan_synapse_migration",
    "sqlserver_db_connector",
    "synapse_db_connector",
]
