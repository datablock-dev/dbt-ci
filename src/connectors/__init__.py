"""Init file for connectors module."""
from argparse import Namespace
import sys
from typing import Dict, Final, Tuple
from src.schema import ConnectorConfig, SupportedConnectors, StorageConnector, StorageConnectorConfig, SupportedStorageConnectors
from src.connectors.aws.storage import (
    aws_download_json,
    aws_storage_client,
    aws_upload_json
)
from src.connectors.google.storage import (
    google_storage_client,
    google_download_json,
    google_upload_json
)
from src.connectors.google.bigquery import (
    bigquery_client,
    bigquery_ephemeral_strategy,
    bigquery_delete_strategy,
    bigquery_migration_strategy
)

DB_CONNECTORS: Final[dict[SupportedConnectors, ConnectorConfig]] = {
    "bigquery": {
        "client": bigquery_client,
        "ephemeral": bigquery_ephemeral_strategy,
        "delete": bigquery_delete_strategy,
        "migration": bigquery_migration_strategy
    }
}

STORAGE_URI_PREFIXES: Final[dict[str, str]] = {
    "gs": "google",
    "s3": "aws"
}

STORAGE_CONNECTORS: Final[dict[SupportedStorageConnectors, StorageConnectorConfig]] = {
    "aws": {
        "name": "AWS S3",
        "client": aws_storage_client,
        "upload": aws_upload_json,
        "download": aws_download_json,
    },
    "google": {
        "name": "Google Cloud Storage",
        "client": google_storage_client,
        "upload": google_upload_json,
        "download": google_download_json,
    }
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
    storage_connector = STORAGE_CONNECTORS.get(STORAGE_URI_PREFIXES[provider])
    if storage_connector is None:
        print(f"No storage connector found for provider '{provider}'.")
        sys.exit(1)

    return storage_connector, uri

def get_connector(connector: SupportedConnectors) -> ConnectorConfig | dict[SupportedConnectors, ConnectorConfig]:
    """Factory function to get the appropriate connector based on configuration."""
    if connector not in DB_CONNECTORS:
        print(f"Connector '{connector}' is not supported.")
        sys.exit(1)

    return DB_CONNECTORS[connector]


__init__ = [
    "get_connector",
]
