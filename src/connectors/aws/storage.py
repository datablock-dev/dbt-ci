
import boto3

def aws_storage_client():
    """Initialize AWS S3 client."""
    return boto3.client("s3")