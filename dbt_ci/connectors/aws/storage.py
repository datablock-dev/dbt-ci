"""Storage connector for AWS S3 interactions."""
import json
import boto3
from dbt_ci.schema import DBTManifest

def aws_storage_client():
    """Initialize AWS S3 client."""
    return boto3.client("s3")

def aws_upload_json(uri: str, data: dict) -> None:
    """Upload a JSON object to the specified S3 URI."""
    if not uri.startswith("s3://"):
        raise ValueError(f"Invalid S3 URI: {uri}. Must start with 's3://'.")
    
    # Parse bucket name and key from URI
    path_parts = uri[5:].split("/", 1)
    bucket_name = path_parts[0]
    key = path_parts[1] if len(path_parts) > 1 else ""

    try:
        client = aws_storage_client()
        client.put_object(Bucket=bucket_name, Key=key, Body=json.dumps(data), ContentType="application/json")
        print(f"Successfully uploaded JSON to {uri}")
    except Exception as e:
        raise RuntimeError(f"Failed to upload JSON to {uri}: {e}")
    
def aws_download_json(uri: str) -> DBTManifest:
    """Download and parse a JSON object from the specified S3 URI."""
    if not uri.startswith("s3://"):
        raise ValueError(f"Invalid S3 URI: {uri}. Must start with 's3://'.")
    
    # Parse bucket name and key from URI
    path_parts = uri[5:].split("/", 1)
    bucket_name = path_parts[0]
    key = path_parts[1] if len(path_parts) > 1 else ""

    try:
        client = aws_storage_client()
        response = client.get_object(Bucket=bucket_name, Key=key)
        contents = response['Body'].read().decode('utf-8')
        return json.loads(contents)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse JSON from {uri}: {e}")
    except Exception as e:
        raise RuntimeError(f"Failed to download JSON from {uri}: {e}")