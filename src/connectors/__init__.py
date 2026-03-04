"""Init file for connectors module."""
import sys
from typing import Final, cast
from src.schema import ConnectorConfig, SupportedConnectors, StorageConnectorConfig, SupportedStorageConnectors
from src.connectors.aws import aws_storage_connector
from src.connectors.google import bigquery_db_connector, bigquery_storage_connector

DB_CONNECTORS: Final[dict[SupportedConnectors, ConnectorConfig]] = {
    "bigquery": bigquery_db_connector
}

STORAGE_URI_PREFIXES: Final[dict[str, str]] = {
    "gs": "google",
    "s3": "aws"
}

STORAGE_CONNECTORS: Final[dict[SupportedStorageConnectors, StorageConnectorConfig]] = {
    "aws": aws_storage_connector,
    "google": bigquery_storage_connector
}

def init_storage_connector(uri: str | None) -> tuple[StorageConnectorConfig, str] | None:
    """Resolve state manifest path with state URI if provided."""
    if uri is None:
        return None
    provider = uri.split("://")[0]
    if provider not in STORAGE_URI_PREFIXES:
        print(f"Storage provider '{provider}' is not supported. Supported providers: {list(STORAGE_URI_PREFIXES.keys())}")
        sys.exit(1)

    # Now get the configs
    storage_connector = STORAGE_CONNECTORS.get(cast(SupportedStorageConnectors, STORAGE_URI_PREFIXES[provider]))
    if storage_connector is None:
        print(f"No storage connector found for provider '{provider}'.")
        sys.exit(1)

    return storage_connector, uri

def get_connector(connector: SupportedConnectors) -> ConnectorConfig | None:
    """Factory function to get the appropriate connector based on configuration."""
    if connector not in DB_CONNECTORS:
        print(f"Connector '{connector}' is not supported.")
        sys.exit(1)

    return DB_CONNECTORS.get(connector)


__init__ = [
    "get_connector",
]
