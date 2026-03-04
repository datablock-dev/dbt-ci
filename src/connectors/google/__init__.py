from src.connectors.google.storage import (
    google_storage_client,
    google_download_json,
    google_upload_json
)
from src.connectors.google.bigquery import (
    bigquery_client,
    bigquery_create_datasets,
    bigquery_create_tables,
    bigquery_delete_datasets,
    bigquery_delete_tables,
    bigquery_ephemeral_strategy,
    bigquery_delete_strategy,
    bigquery_migration_strategy,
    bigquery_query
)
from src.schema import ConnectorConfig, StorageConnectorConfig

bigquery_storage_connector: StorageConnectorConfig = {
    "name": "Google Cloud Storage",
    "client": google_storage_client,
    "upload": google_upload_json,
    "download": google_download_json,
}

bigquery_db_connector: ConnectorConfig = {
    "client": bigquery_client,
    "strategies": {
        "ephemeral": bigquery_ephemeral_strategy,
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

__init__ = [
    "bigquery_storage_connector",
    "bigquery_db_connector"
]