"""Init file for connectors module."""
import logging
from typing import Final, cast
from dbt_ci.schema import (
    ConnectorConfig,
    NativeConnectors,
    SupportedConnectors,
    StorageConnectorConfig,
    SupportedStorageConnectors,
)
from dbt_ci.connectors.aws import aws_storage_connector
from dbt_ci.connectors.generic import generic_db_connector
from dbt_ci.connectors.google import bigquery_db_connector, bigquery_storage_connector

logger = logging.getLogger(__name__)

# Adapters with a warehouse-native implementation. Everything else is served by the generic
# connector, which reaches the warehouse through `dbt run-operation`.
DB_CONNECTORS: Final[dict[NativeConnectors, ConnectorConfig]] = {
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
        raise ValueError(f"Storage provider '{provider}' is not supported. Supported providers: {list(STORAGE_URI_PREFIXES.keys())}")

    # Now get the configs
    storage_connector = STORAGE_CONNECTORS.get(cast(SupportedStorageConnectors, STORAGE_URI_PREFIXES[provider]))
    if storage_connector is None:
        raise ValueError(f"No storage connector found for provider '{provider}'.")

    return storage_connector, uri

def get_connector(connector: SupportedConnectors) -> ConnectorConfig | None:
    """Factory function to get the appropriate connector based on configuration."""
    native_connector = DB_CONNECTORS.get(cast(NativeConnectors, connector))
    if native_connector is not None:
        return native_connector

    logger.debug(
        f"No native connector for adapter '{connector}'; using the generic connector, which "
        "runs SQL through 'dbt run-operation'."
    )
    return generic_db_connector


__all__ = [
    "generic_db_connector",
    "get_connector",
    "init_storage_connector",
]
