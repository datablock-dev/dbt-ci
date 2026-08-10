from dbt_ci.schema import ConnectorConfig, StorageConnectorConfig
from dbt_ci.connectors.google.storage import (
    google_storage_client,
    google_download_json,
    google_upload
)
from dbt_ci.connectors.google.bigquery import (
    bigquery,
    bigquery_client,
    bigquery_create_datasets,
    bigquery_create_tables,
    bigquery_delete_datasets,
    bigquery_delete_tables,
    bigquery_delete_strategy,
    bigquery_migration_strategy,
    bigquery_query
)

bigquery_storage_connector: StorageConnectorConfig = {
    "name": "Google Cloud Storage",
    "client": google_storage_client,
    "upload": google_upload,
    "download": google_download_json,
}

bigquery_db_connector: ConnectorConfig = {
    "client": bigquery_client,
    "strategies": {
        #"ephemeral": bigquery_ephemeral_strategy,
        "delete": bigquery_delete_strategy,
        "migration": bigquery_migration_strategy
    },
    "methods": {
        "query": bigquery_query,
        "create_datasets": bigquery_create_datasets,
        "delete_datasets": bigquery_delete_datasets,
        "create_tables": bigquery_create_tables,
        "delete_tables": bigquery_delete_tables
    }
}


def is_available() -> bool:
    """Report whether google-cloud-bigquery is installed, so the registry can fall back if not."""
    return bigquery is not None

__init__ = [
    "bigquery_storage_connector",
    "bigquery_db_connector"
]