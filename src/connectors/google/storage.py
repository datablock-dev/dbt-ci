import json
from google.cloud import storage
from src.schema import DBTManifest

def google_storage_client():
    """Initialize Google Cloud Storage client."""
    return storage.Client()

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