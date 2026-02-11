"""Init file for connectors module."""
import sys
from typing import Dict
from src.schema import ConnectorConfig, SupportedConnectors
from src.connectors.bigquery import (
    bigquery_client,
    bigquery_ephemeral_strategy
)

# Create a type

def get_connector(connector: SupportedConnectors):
    """Factory function to get the appropriate connector based on configuration."""
    
    CONNECTORS: Dict[SupportedConnectors, ConnectorConfig] = {
        "bigquery": {
            "client": bigquery_client,
            "ephemeral": bigquery_ephemeral_strategy
        }
    }

    if connector not in CONNECTORS:
        print(f"Connector '{connector}' is not supported.")
        sys.exit(1)

    return CONNECTORS[connector]

__init__ = [
    "get_connector",
]