from __future__ import annotations

import json
from typing import Any
from dbt_ci.schema import DBTManifest
from dbt_ci.utilities.optional_imports import require

try:  # google-cloud-storage ships in the optional "gcp" extra.
    from google.cloud import storage
except ImportError:  # pragma: no cover - exercised only without the extra installed
    storage = None

def google_storage_client():
    """Initialize Google Cloud Storage client."""
    return require(storage, "gcp", "GCS state storage").Client()

def google_upload_json(uri: str, data: dict) -> None:
    """Upload a JSON object to the specified GCS URI."""
    if not uri.startswith("gs://"):
        raise ValueError(f"Invalid GCS URI: {uri}. Must start with 'gs://'.")
    
    # Parse bucket name and blob name from URI
    path_parts = uri[5:].split("/", 1)
    bucket_name = path_parts[0]
    blob_name = path_parts[1] if len(path_parts) > 1 else ""

    try:
        client = google_storage_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        blob.upload_from_string(json.dumps(data), content_type="application/json")
        print(f"Successfully uploaded JSON to {uri}")
    except Exception as e:
        raise RuntimeError(f"Failed to upload JSON to {uri}: {e}")

def google_upload(uri: str, data: Any, content_type: str = "application/json") -> None:
    """Upload data to the specified GCS URI with the given content type."""
    if not uri.startswith("gs://"):
        raise ValueError(f"Invalid GCS URI: {uri}. Must start with 'gs://'")

    path_parts = uri[5:].split("/", 1)
    bucket_name = path_parts[0]
    blob_name = path_parts[1] if len(path_parts) > 1 else ""

    body: str | bytes = json.dumps(data) if content_type == "application/json" else data
    try:
        client = google_storage_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        blob.upload_from_string(body, content_type=content_type)
        print(f"Successfully uploaded to {uri}")
    except Exception as e:
        raise RuntimeError(f"Failed to upload to {uri}: {e}")

def google_download_json(uri: str) -> DBTManifest:
    """Download and parse a JSON blob from GCS using a URI.
    
    Args:
        uri: GCS URI in format gs://bucket-name/path/to/file.json
        
    Returns:
        Parsed JSON as a DBTManifest dictionary
        
    Raises:
        ValueError: If URI format is invalid
        RuntimeError: If download fails or JSON is invalid
    """
    if not uri.startswith("gs://"):
        raise ValueError(f"Invalid GCS URI: {uri}. Must start with 'gs://'.")
    
    # Parse bucket name and blob name from URI
    path_parts = uri[5:].split("/", 1)
    bucket_name = path_parts[0]
    blob_name = path_parts[1] if len(path_parts) > 1 else ""
    
    if not blob_name:
        raise ValueError(f"Invalid GCS URI: {uri}. Must include a blob path after bucket name.")
    
    try:
        client = google_storage_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        contents = blob.download_as_bytes()
        return json.loads(contents.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse JSON from {uri}: {e}")
    except Exception as e:
        raise RuntimeError(f"Failed to download blob from {uri}: {e}")