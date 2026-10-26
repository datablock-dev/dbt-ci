"""Unit tests for the GCS and S3 state storage connectors, with the cloud clients mocked."""

import json
from unittest.mock import MagicMock, patch

import pytest

from dbt_ci.connectors.aws.storage import aws_download_json, aws_upload
from dbt_ci.connectors.google.storage import google_download_json, google_upload


@pytest.fixture
def gcs_client():
    """A mocked GCS client; the blob it hands out records uploads and serves downloads."""
    client = MagicMock()
    with patch("dbt_ci.connectors.google.storage.google_storage_client", return_value=client):
        yield client


@pytest.fixture
def s3_client():
    """A mocked boto3 S3 client."""
    client = MagicMock()
    with patch("dbt_ci.connectors.aws.storage.aws_storage_client", return_value=client):
        yield client


def gcs_blob(client: MagicMock) -> MagicMock:
    """Return the blob mock any bucket/blob lookup on the client resolves to."""
    return client.bucket.return_value.blob.return_value


class TestGoogleStorage:
    """gs:// URIs are split into bucket and blob, and payloads are serialised once."""

    def test_upload_json(self, gcs_client):
        """JSON payloads are serialised and stored under the blob path."""
        google_upload("gs://state/prod/manifest.json", {"nodes": {}})

        gcs_client.bucket.assert_called_once_with("state")
        gcs_client.bucket.return_value.blob.assert_called_once_with("prod/manifest.json")
        gcs_blob(gcs_client).upload_from_string.assert_called_once_with(
            '{"nodes": {}}', content_type="application/json"
        )

    def test_upload_text_is_not_serialised(self, gcs_client):
        """The log upload passes text through unchanged."""
        google_upload("gs://state/logs.txt", "line 1\nline 2", "text/plain")

        gcs_blob(gcs_client).upload_from_string.assert_called_once_with(
            "line 1\nline 2", content_type="text/plain"
        )

    def test_upload_failure_keeps_its_cause(self, gcs_client):
        """A client error is reported with the URI, and the original error is chained."""
        cause = PermissionError("403 Forbidden")
        gcs_blob(gcs_client).upload_from_string.side_effect = cause

        with pytest.raises(RuntimeError, match="Failed to upload to gs://state/m.json") as exc:
            google_upload("gs://state/m.json", {})
        assert exc.value.__cause__ is cause

    def test_download_json(self, gcs_client):
        """A downloaded manifest is parsed from bytes."""
        gcs_blob(gcs_client).download_as_bytes.return_value = json.dumps({"nodes": {}}).encode()

        assert google_download_json("gs://state/prod/manifest.json") == {"nodes": {}}
        gcs_client.bucket.return_value.blob.assert_called_once_with("prod/manifest.json")

    def test_download_invalid_json(self, gcs_client):
        """A blob that is not JSON is a parse error, not a download error."""
        gcs_blob(gcs_client).download_as_bytes.return_value = b"<html>"

        with pytest.raises(RuntimeError, match="Failed to parse JSON"):
            google_download_json("gs://state/manifest.json")

    @pytest.mark.parametrize("uri", ["s3://state/manifest.json", "state/manifest.json"])
    def test_rejects_other_schemes(self, uri):
        """Only gs:// URIs are accepted, before any client is created."""
        with pytest.raises(ValueError, match="Must start with 'gs://'"):
            google_download_json(uri)
        with pytest.raises(ValueError, match="Must start with 'gs://'"):
            google_upload(uri, {})

    def test_download_needs_a_blob_path(self):
        """A bare bucket cannot hold the manifest."""
        with pytest.raises(ValueError, match="Must include a blob path"):
            google_download_json("gs://state")


class TestS3Storage:
    """s3:// URIs are split into bucket and key, and payloads are serialised once."""

    def test_upload_json(self, s3_client):
        """JSON payloads are serialised and stored under the key."""
        aws_upload("s3://state/prod/manifest.json", {"nodes": {}})

        s3_client.put_object.assert_called_once_with(
            Bucket="state",
            Key="prod/manifest.json",
            Body='{"nodes": {}}',
            ContentType="application/json",
        )

    def test_upload_text_is_not_serialised(self, s3_client):
        """The log upload passes text through unchanged."""
        aws_upload("s3://state/logs.txt", "line 1", "text/plain")

        assert s3_client.put_object.call_args.kwargs["Body"] == "line 1"

    def test_upload_failure_keeps_its_cause(self, s3_client):
        """A client error is reported with the URI, and the original error is chained."""
        cause = PermissionError("AccessDenied")
        s3_client.put_object.side_effect = cause

        with pytest.raises(RuntimeError, match="Failed to upload to s3://state/m.json") as exc:
            aws_upload("s3://state/m.json", {})
        assert exc.value.__cause__ is cause

    def test_download_json(self, s3_client):
        """A downloaded manifest is read from the response body and parsed."""
        s3_client.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b'{"nodes": {}}'))
        }

        assert aws_download_json("s3://state/prod/manifest.json") == {"nodes": {}}
        s3_client.get_object.assert_called_once_with(Bucket="state", Key="prod/manifest.json")

    def test_download_invalid_json(self, s3_client):
        """An object that is not JSON is a parse error, not a download error."""
        s3_client.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=b"x"))}

        with pytest.raises(RuntimeError, match="Failed to parse JSON"):
            aws_download_json("s3://state/manifest.json")

    def test_download_failure_keeps_its_cause(self, s3_client):
        """A missing object is reported with the URI."""
        cause = KeyError("NoSuchKey")
        s3_client.get_object.side_effect = cause

        with pytest.raises(RuntimeError, match="Failed to download JSON from s3://") as exc:
            aws_download_json("s3://state/manifest.json")
        assert exc.value.__cause__ is cause

    @pytest.mark.parametrize("uri", ["gs://state/manifest.json", "state/manifest.json"])
    def test_rejects_other_schemes(self, uri):
        """Only s3:// URIs are accepted, before any client is created."""
        with pytest.raises(ValueError, match="Must start with 's3://'"):
            aws_download_json(uri)
        with pytest.raises(ValueError, match="Must start with 's3://'"):
            aws_upload(uri, {})
