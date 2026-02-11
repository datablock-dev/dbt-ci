"""Helper functions for Google Cloud Storage connector."""
import json
from typing import Any, Dict, Optional
from google.cloud import storage
from google.cloud.exceptions import GoogleCloudError

def storage_client():
    """Initialize Google Cloud Storage client."""
    return storage.Client()

def upload_blob(bucket_name: str, source_file_name: str, destination_blob_name: str, content_type: Optional[str] = None) -> str:
    """Upload a file to the bucket.
    
    Args:
        bucket_name: Name of the GCS bucket
        source_file_name: Path to the local file to upload
        destination_blob_name: Destination path in the bucket
        content_type: Optional MIME type for the file
        
    Returns:
        The public URL of the uploaded blob
        
    Raises:
        GoogleCloudError: If upload fails
    """
    try:
        client = storage_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(destination_blob_name)
        
        if content_type:
            blob.content_type = content_type
        
        blob.upload_from_filename(source_file_name)
        return f"gs://{bucket_name}/{destination_blob_name}"
    except GoogleCloudError as e:
        raise RuntimeError(f"Failed to upload {source_file_name} to {bucket_name}/{destination_blob_name}: {e}")

def upload_blob_from_memory(bucket_name: str, contents: str, destination_blob_name: str, content_type: Optional[str] = None) -> str:
    """Upload a string as a blob to the bucket.
    
    Args:
        bucket_name: Name of the GCS bucket
        contents: String content to upload
        destination_blob_name: Destination path in the bucket
        content_type: Optional MIME type (e.g., 'text/plain', 'text/csv')
        
    Returns:
        The public URL of the uploaded blob
        
    Raises:
        GoogleCloudError: If upload fails
    """
    try:
        client = storage_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(destination_blob_name)
        
        if content_type:
            blob.content_type = content_type
        
        blob.upload_from_string(contents)
        return f"gs://{bucket_name}/{destination_blob_name}"
    except GoogleCloudError as e:
        raise RuntimeError(f"Failed to upload string to {bucket_name}/{destination_blob_name}: {e}")

def upload_json(bucket_name: str, data: Dict[str, Any], destination_blob_name: str, indent: Optional[int] = 2) -> str:
    """Upload a Python dictionary as JSON to the bucket.
    
    Args:
        bucket_name: Name of the GCS bucket
        data: Python dictionary to upload as JSON
        destination_blob_name: Destination path in the bucket
        indent: JSON indentation (default: 2, use None for compact)
        
    Returns:
        The public URL of the uploaded blob
        
    Raises:
        GoogleCloudError: If upload fails
        TypeError: If data is not JSON serializable
    """
    try:
        json_string = json.dumps(data, indent=indent)
        client = storage_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(destination_blob_name)
        
        blob.content_type = 'application/json'
        blob.upload_from_string(json_string)
        return f"gs://{bucket_name}/{destination_blob_name}"
    except (GoogleCloudError, TypeError) as e:
        raise RuntimeError(f"Failed to upload JSON to {bucket_name}/{destination_blob_name}: {e}")

def download_blob(bucket_name: str, source_blob_name: str, destination_file_name: str) -> str:
    """Download a blob from the bucket to a local file.
    
    Args:
        bucket_name: Name of the GCS bucket
        source_blob_name: Path to the blob in the bucket
        destination_file_name: Local path to save the file
        
    Returns:
        The local file path
        
    Raises:
        GoogleCloudError: If download fails
    """
    try:
        client = storage_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(source_blob_name)
        blob.download_to_filename(destination_file_name)
        return destination_file_name
    except GoogleCloudError as e:
        raise RuntimeError(f"Failed to download {bucket_name}/{source_blob_name} to {destination_file_name}: {e}")

def download_blob_into_memory(bucket_name: str, blob_name: str) -> str:
    """Download a blob from the bucket into memory and return its contents as a string.
    
    Args:
        bucket_name: Name of the GCS bucket
        blob_name: Path to the blob in the bucket
        
    Returns:
        The blob contents as a string
        
    Raises:
        GoogleCloudError: If download fails
        UnicodeDecodeError: If blob cannot be decoded as UTF-8
    """
    try:
        client = storage_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        contents = blob.download_as_bytes()
        return contents.decode("utf-8")
    except GoogleCloudError as e:
        raise RuntimeError(f"Failed to download {bucket_name}/{blob_name}: {e}")
    except UnicodeDecodeError as e:
        raise RuntimeError(f"Failed to decode blob {bucket_name}/{blob_name} as UTF-8: {e}")

def download_json(bucket_name: str, blob_name: str) -> Dict[str, Any]:
    """Download and parse a JSON blob from the bucket.
    
    Args:
        bucket_name: Name of the GCS bucket
        blob_name: Path to the JSON blob in the bucket
        
    Returns:
        Parsed JSON as a Python dictionary
        
    Raises:
        GoogleCloudError: If download fails
        json.JSONDecodeError: If blob is not valid JSON
    """
    try:
        client = storage_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        contents = blob.download_as_bytes()
        return json.loads(contents.decode("utf-8"))
    except GoogleCloudError as e:
        raise RuntimeError(f"Failed to download JSON from {bucket_name}/{blob_name}: {e}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse JSON from {bucket_name}/{blob_name}: {e}")
