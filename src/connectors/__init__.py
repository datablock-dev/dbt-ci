"""Init file for connectors module."""
import sys
from typing import Dict
from src.schema import ConnectorConfig, SupportedConnectors
from src.connectors.bigquery import (
    bigquery_client,
    bigquery_ephemeral_strategy,
    bigquery_delete_table
)

# Create a type

def get_connector(connector: SupportedConnectors):
    """Factory function to get the appropriate connector based on configuration."""
    
    connectors: Dict[SupportedConnectors, ConnectorConfig] = {
        "bigquery": {
            "client": bigquery_client,
            "ephemeral": bigquery_ephemeral_strategy,
            "delete": bigquery_delete_table,
            "migration": None
        }
    }

    if connector not in connectors:
        print(f"Connector '{connector}' is not supported.")
        sys.exit(1)

    return connectors[connector]

__init__ = [
    "get_connector",
]
