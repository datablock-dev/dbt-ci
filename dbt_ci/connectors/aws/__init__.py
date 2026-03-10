from dbt_ci.schema import ConnectorConfig, StorageConnectorConfig
from dbt_ci.connectors.aws.storage import (
    aws_download_json,
    aws_storage_client,
    aws_upload_json
)

aws_storage_connector: StorageConnectorConfig = {
    "name": "AWS S3",
    "client": aws_storage_client,
    "upload": aws_upload_json,
    "download": aws_download_json,
}

__init__ = [
    "aws_storage_connector",
]