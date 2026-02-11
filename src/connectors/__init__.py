"""Init file for connectors module."""
import sys
from typing import Dict, Final
from src.schema import ConnectorConfig, SupportedConnectors
from src.connectors.bigquery import (
    bigquery_client,
    bigquery_ephemeral_strategy,
    bigquery_delete_table
)

CONNECTORS: Final[Dict[SupportedConnectors, ConnectorConfig]] = {
    "bigquery": {
        "client": bigquery_client,
        "ephemeral": bigquery_ephemeral_strategy,
        "delete": bigquery_delete_table,
        "migration": None
    }
}


def get_connector(connector: SupportedConnectors) -> ConnectorConfig | Dict[SupportedConnectors, ConnectorConfig]:
    """Factory function to get the appropriate connector based on configuration."""
    if connector not in CONNECTORS:
        print(f"Connector '{connector}' is not supported.")
        sys.exit(1)

    return CONNECTORS[connector]


__init__ = [
    "get_connector",
]
