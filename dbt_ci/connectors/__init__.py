"""Init file for connectors module."""
import importlib
import logging
from typing import Final, NamedTuple, cast
from dbt_ci.schema import (
    ConnectorConfig,
    SupportedConnectors,
    StorageConnectorConfig,
    SupportedStorageConnectors,
)
from dbt_ci.connectors.aws import aws_storage_connector
from dbt_ci.connectors.generic import generic_db_connector
from dbt_ci.connectors.google import bigquery_storage_connector

logger = logging.getLogger(__name__)


class NativeConnector(NamedTuple):
    """Where a native connector lives and which extra installs the driver it needs."""
    module: str
    attribute: str
    extra: str


# Native connectors talk to the warehouse directly, through its own driver. They are
# imported lazily and behind an extra: importing them eagerly would make every install
# pay for every warehouse.
NATIVE_CONNECTORS: Final[dict[str, NativeConnector]] = {
    "bigquery": NativeConnector("dbt_ci.connectors.google", "bigquery_db_connector", "gcp"),
    "snowflake": NativeConnector("dbt_ci.connectors.snowflake", "snowflake_db_connector", "snowflake"),
    "redshift": NativeConnector("dbt_ci.connectors.redshift", "redshift_db_connector", "redshift"),
    "databricks": NativeConnector("dbt_ci.connectors.databricks", "databricks_db_connector", "databricks"),
    "synapse": NativeConnector("dbt_ci.connectors.azure", "synapse_db_connector", "azure"),
    "fabric": NativeConnector("dbt_ci.connectors.azure", "fabric_db_connector", "azure"),
    "sqlserver": NativeConnector("dbt_ci.connectors.azure", "sqlserver_db_connector", "azure"),
    "postgres": NativeConnector("dbt_ci.connectors.postgres", "postgres_db_connector", "postgres"),
    "mysql": NativeConnector("dbt_ci.connectors.mysql", "mysql_db_connector", "mysql"),
    "mariadb": NativeConnector("dbt_ci.connectors.mysql", "mysql_db_connector", "mysql"),
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

def load_native_connector(connector: SupportedConnectors) -> ConnectorConfig | None:
    """
    Return the native connector for an adapter type, or None if it cannot be used.

    None covers both "dbt-ci has no native connector for this adapter" and "it has one but
    the extra providing its driver is not installed". Neither is an error: the caller falls
    back to the generic connector, so the commands still work, just more slowly.
    """
    native = NATIVE_CONNECTORS.get(connector)
    if native is None:
        return None

    try:
        module = importlib.import_module(native.module)
    except ImportError as e:  # pragma: no cover - depends on which extras are installed
        logger.debug(f"Native connector for '{connector}' could not be imported: {e}")
        return None

    # Each adapter package reports whether its driver actually imported. The package itself
    # always imports, since the driver import is guarded, so this is the real check.
    is_available = getattr(module, "is_available", None)
    if is_available is not None and not is_available():
        return None

    return getattr(module, native.attribute, None)

def get_connector(connector: SupportedConnectors) -> ConnectorConfig | None:
    """Factory function to get the appropriate connector based on configuration."""
    native_connector = load_native_connector(connector)
    if native_connector is not None:
        return native_connector

    native = NATIVE_CONNECTORS.get(connector)
    if native is not None:
        logger.info(
            f"A native '{connector}' connector is available but the '{native.extra}' extra is "
            f"not installed, so SQL will run through 'dbt run-operation' instead. Install it "
            f"with: pip install 'dbt-ci[{native.extra}]'"
        )
    else:
        logger.debug(
            f"No native connector for adapter '{connector}'; using the generic connector, "
            "which runs SQL through 'dbt run-operation'."
        )
    return generic_db_connector


__all__ = [
    "generic_db_connector",
    "get_connector",
    "init_storage_connector",
    "load_native_connector",
]
