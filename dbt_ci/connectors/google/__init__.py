from dbt_ci.schema import ConnectorConfig, StorageConnectorConfig
from dbt_ci.connectors.google.storage import (
    google_storage_client,
    google_download_json,
    google_upload,
)
from dbt_ci.connectors.google.bigquery import (
    bigquery_client,
    bigquery_delete_datasets,
    bigquery_delete_strategy,
    bigquery_migration_strategy,
)

bigquery_storage_connector: StorageConnectorConfig = {
    "name": "Google Cloud Storage",
    "client": google_storage_client,
    "upload": google_upload,
    "download": google_download_json,
}

bigquery_db_connector: ConnectorConfig = {
    "client": bigquery_client,
    "strategies": {"delete": bigquery_delete_strategy, "migration": bigquery_migration_strategy},
    "methods": {
        "delete_datasets": bigquery_delete_datasets,
    },
}

__init__ = ["bigquery_storage_connector", "bigquery_db_connector"]
