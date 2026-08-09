"""Storage connector for AWS S3 interactions."""
from __future__ import annotations

import json
from typing import Any
from dbt_ci.schema import DBTManifest
from dbt_ci.utilities.optional_imports import require

try:  # boto3 ships in the optional "aws" extra.
    import boto3
except ImportError:  # pragma: no cover - exercised only without the extra installed
    boto3 = None

def aws_storage_client():
    """Initialize AWS S3 client."""
    return require(boto3, "aws", "S3 state storage").client("s3")

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
    
def aws_upload(uri: str, data: Any, content_type: str = "application/json") -> None:
    """Upload data to the specified S3 URI with the given content type."""
    if not uri.startswith("s3://"):
        raise ValueError(f"Invalid S3 URI: {uri}. Must start with 's3://'")

    path_parts = uri[5:].split("/", 1)
    bucket_name = path_parts[0]
    key = path_parts[1] if len(path_parts) > 1 else ""

    body: str | bytes = json.dumps(data) if content_type == "application/json" else data
    try:
        client = aws_storage_client()
        client.put_object(Bucket=bucket_name, Key=key, Body=body, ContentType=content_type)
        print(f"Successfully uploaded to {uri}")
    except Exception as e:
        raise RuntimeError(f"Failed to upload to {uri}: {e}")

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