"""Unit tests for finalize upload logic."""
import pytest
from unittest.mock import MagicMock, patch, call
from argparse import Namespace
from dbt_ci.commands.finalize.upload import (
    finalize_upload_files,
    upload_cache,
    upload_logs,
    upload_manifest,
)
from dbt_ci.utilities.logging import LOG_FILE_NAME


def _make_args(**kwargs) -> Namespace:
    defaults = dict(artifacts_uri=None, files=("manifest",))
    defaults.update(kwargs)
    return Namespace(**defaults)


def _make_storage_function():
    return MagicMock()


# ---------------------------------------------------------------------------
# finalize_upload_files — high-level dispatch
# ---------------------------------------------------------------------------

class TestFinalizeUploadFiles:

    def test_skips_when_no_artifacts_uri(self):
        """No upload should happen when artifacts_uri is not provided."""
        args = _make_args(artifacts_uri=None, files=("manifest",))
        with patch("dbt_ci.commands.finalize.upload.CacheManager") as mock_cm, \
             patch("dbt_ci.commands.finalize.upload.init_storage_connector") as mock_storage:
            finalize_upload_files(args)
            mock_storage.assert_not_called()

    def test_skips_when_no_files(self):
        """Upload should be skipped (with info log) when files list is empty."""
        args = _make_args(artifacts_uri="gs://bucket/path", files=())
        mock_connector = MagicMock()
        mock_connector.get.return_value = _make_storage_function()
        with patch("dbt_ci.commands.finalize.upload.CacheManager"), \
             patch("dbt_ci.commands.finalize.upload.init_storage_connector") as mock_init, \
             patch("dbt_ci.commands.finalize.upload.logger") as mock_logger:
            mock_init.return_value = (mock_connector, "gs://bucket/path")
            finalize_upload_files(args)
            mock_logger.info.assert_any_call(
                "No files specified for upload. Please specify which files to upload using the --files argument. Skipping artifact upload."
            )

    def test_skips_when_no_storage_connector(self):
        """Upload should be skipped with a warning when no connector is found."""
        args = _make_args(artifacts_uri="gs://bucket/path", files=("manifest",))
        with patch("dbt_ci.commands.finalize.upload.CacheManager"), \
             patch("dbt_ci.commands.finalize.upload.init_storage_connector", return_value=None), \
             patch("dbt_ci.commands.finalize.upload.logger") as mock_logger:
            finalize_upload_files(args)
            mock_logger.warning.assert_any_call(
                "No valid storage connector found for artifact upload. Skipping artifact upload."
            )

    def test_skips_when_no_upload_function_on_connector(self):
        """Upload should be skipped when the connector has no 'upload' key."""
        args = _make_args(artifacts_uri="gs://bucket/path", files=("manifest",))
        mock_connector = {"name": "test", "upload": None, "download": MagicMock()}
        with patch("dbt_ci.commands.finalize.upload.CacheManager"), \
             patch("dbt_ci.commands.finalize.upload.init_storage_connector",
                   return_value=(mock_connector, "gs://bucket/path")), \
             patch("dbt_ci.commands.finalize.upload.logger") as mock_logger:
            finalize_upload_files(args)
            mock_logger.warning.assert_any_call(
                "No upload function found for resolved storage connector. Skipping artifact upload."
            )

    def test_calls_correct_upload_function_for_manifest(self):
        """upload_manifest should be called when 'manifest' is in files."""
        args = _make_args(artifacts_uri="gs://bucket/path", files=("manifest",))
        mock_storage_fn = _make_storage_function()
        mock_connector = {"name": "GCS", "upload": mock_storage_fn, "download": MagicMock()}
        mock_upload_manifest = MagicMock()
        with patch("dbt_ci.commands.finalize.upload.CacheManager") as mock_cm, \
             patch("dbt_ci.commands.finalize.upload.init_storage_connector",
                   return_value=(mock_connector, "gs://bucket/path")), \
             patch.dict("dbt_ci.commands.finalize.upload.UPLOAD_MAPPING",
                        {"manifest": mock_upload_manifest}):
            finalize_upload_files(args)
            mock_upload_manifest.assert_called_once_with(
                "gs://bucket/path", mock_cm.return_value, mock_storage_fn
            )

    def test_calls_correct_upload_function_for_cache(self):
        """upload_cache should be called when 'cache' is in files."""
        args = _make_args(artifacts_uri="s3://bucket/path", files=("cache",))
        mock_storage_fn = _make_storage_function()
        mock_connector = {"name": "S3", "upload": mock_storage_fn, "download": MagicMock()}
        mock_upload_cache = MagicMock()
        with patch("dbt_ci.commands.finalize.upload.CacheManager") as mock_cm, \
             patch("dbt_ci.commands.finalize.upload.init_storage_connector",
                   return_value=(mock_connector, "s3://bucket/path")), \
             patch.dict("dbt_ci.commands.finalize.upload.UPLOAD_MAPPING",
                        {"cache": mock_upload_cache}):
            finalize_upload_files(args)
            mock_upload_cache.assert_called_once_with(
                "s3://bucket/path", mock_cm.return_value, mock_storage_fn
            )

    def test_calls_correct_upload_function_for_logs(self):
        """upload_logs should be called when 'log' is in files."""
        args = _make_args(artifacts_uri="gs://bucket/path", files=("log",))
        mock_storage_fn = _make_storage_function()
        mock_connector = {"name": "GCS", "upload": mock_storage_fn, "download": MagicMock()}
        mock_upload_logs = MagicMock()
        with patch("dbt_ci.commands.finalize.upload.CacheManager") as mock_cm, \
             patch("dbt_ci.commands.finalize.upload.init_storage_connector",
                   return_value=(mock_connector, "gs://bucket/path")), \
             patch.dict("dbt_ci.commands.finalize.upload.UPLOAD_MAPPING",
                        {"log": mock_upload_logs}):
            finalize_upload_files(args)
            mock_upload_logs.assert_called_once_with(
                "gs://bucket/path", mock_cm.return_value, mock_storage_fn
            )

    def test_calls_multiple_upload_functions(self):
        """Both upload functions are called when multiple file types are requested."""
        args = _make_args(artifacts_uri="gs://bucket/path", files=("manifest", "cache"))
        mock_storage_fn = _make_storage_function()
        mock_connector = {"name": "GCS", "upload": mock_storage_fn, "download": MagicMock()}
        mock_upload_manifest = MagicMock()
        mock_upload_cache = MagicMock()
        with patch("dbt_ci.commands.finalize.upload.CacheManager"), \
             patch("dbt_ci.commands.finalize.upload.init_storage_connector",
                   return_value=(mock_connector, "gs://bucket/path")), \
             patch.dict("dbt_ci.commands.finalize.upload.UPLOAD_MAPPING",
                        {"manifest": mock_upload_manifest, "cache": mock_upload_cache}):
            finalize_upload_files(args)
            mock_upload_manifest.assert_called_once()
            mock_upload_cache.assert_called_once()

    def test_unknown_file_type_skipped_with_warning(self):
        """An unknown file type should be skipped and a warning logged."""
        args = _make_args(artifacts_uri="gs://bucket/path", files=("unknown_type",))
        mock_storage_fn = _make_storage_function()
        mock_connector = {"name": "GCS", "upload": mock_storage_fn, "download": MagicMock()}
        with patch("dbt_ci.commands.finalize.upload.CacheManager"), \
             patch("dbt_ci.commands.finalize.upload.init_storage_connector",
                   return_value=(mock_connector, "gs://bucket/path")), \
             patch("dbt_ci.commands.finalize.upload.logger") as mock_logger:
            finalize_upload_files(args)
            mock_logger.warning.assert_any_call(
                "No upload function found for file type 'unknown_type'. Skipping upload for this file type."
            )
            mock_storage_fn.assert_not_called()

    def test_unknown_file_type_does_not_block_valid_types(self):
        """A valid file type should still be uploaded even if a preceding type is unknown."""
        args = _make_args(artifacts_uri="gs://bucket/path", files=("unknown_type", "manifest"))
        mock_storage_fn = _make_storage_function()
        mock_connector = {"name": "GCS", "upload": mock_storage_fn, "download": MagicMock()}
        mock_upload_manifest = MagicMock()
        with patch("dbt_ci.commands.finalize.upload.CacheManager"), \
             patch("dbt_ci.commands.finalize.upload.init_storage_connector",
                   return_value=(mock_connector, "gs://bucket/path")), \
             patch.dict("dbt_ci.commands.finalize.upload.UPLOAD_MAPPING",
                        {"manifest": mock_upload_manifest}):
            finalize_upload_files(args)
            mock_upload_manifest.assert_called_once()


# ---------------------------------------------------------------------------
# Individual upload helpers
# ---------------------------------------------------------------------------

class TestUploadManifest:

    def test_uploads_target_manifest_when_present(self):
        storage_fn = _make_storage_function()
        cache = MagicMock()
        cache.get_cache.side_effect = lambda name=None: {"key": "value"} if name == "target_manifest.json" else None

        upload_manifest("gs://bucket/path", cache, storage_fn)

        storage_fn.assert_called_once_with(
            "gs://bucket/path/manifest.json", {"key": "value"}, "application/json"
        )

    def test_falls_back_to_reference_manifest(self):
        storage_fn = _make_storage_function()
        cache = MagicMock()
        cache.get_cache.side_effect = lambda name=None: (
            None if name == "target_manifest.json" else {"ref": "data"}
        )

        upload_manifest("gs://bucket/path", cache, storage_fn)

        storage_fn.assert_called_once_with(
            "gs://bucket/path/manifest.json", {"ref": "data"}, "application/json"
        )

    def test_skips_when_no_manifest_available(self):
        storage_fn = _make_storage_function()
        cache = MagicMock()
        cache.get_cache.return_value = None

        with patch("dbt_ci.commands.finalize.upload.logger") as mock_logger:
            upload_manifest("gs://bucket/path", cache, storage_fn)

        storage_fn.assert_not_called()
        mock_logger.warning.assert_called_once()


class TestUploadCache:

    def test_uploads_cache_when_present(self):
        storage_fn = _make_storage_function()
        cache = MagicMock()
        cache.get_cache.return_value = {"modified_nodes": {}}

        upload_cache("gs://bucket/path", cache, storage_fn)

        storage_fn.assert_called_once_with(
            "gs://bucket/path/cache.json", {"modified_nodes": {}}, "application/json"
        )

    def test_skips_when_no_cache(self):
        storage_fn = _make_storage_function()
        cache = MagicMock()
        cache.get_cache.return_value = None

        with patch("dbt_ci.commands.finalize.upload.logger") as mock_logger:
            upload_cache("gs://bucket/path", cache, storage_fn)

        storage_fn.assert_not_called()
        mock_logger.warning.assert_called_once()


class TestUploadLogs:

    def test_uploads_logs_as_plain_text(self):
        storage_fn = _make_storage_function()
        cache = MagicMock()
        cache.get_cache.return_value = "some log content"

        upload_logs("gs://bucket/path", cache, storage_fn)

        storage_fn.assert_called_once_with(
            "gs://bucket/path/logs.txt", "some log content", "text/plain"
        )

    def test_reads_the_file_the_logger_actually_writes(self):
        """The log handler writes dbt-ci.log, so reading any other name uploads nothing."""
        storage_fn = _make_storage_function()
        cache = MagicMock()
        cache.get_cache.return_value = "some log content"

        upload_logs("gs://bucket/path", cache, storage_fn)

        cache.get_cache.assert_called_once_with(LOG_FILE_NAME, "txt")

    def test_flushes_buffered_records_before_reading(self):
        """Records still buffered by the handler would otherwise be missing."""
        storage_fn = _make_storage_function()
        cache = MagicMock()
        cache.get_cache.return_value = "some log content"

        with patch("dbt_ci.commands.finalize.upload.flush_log_file") as mock_flush:
            upload_logs("gs://bucket/path", cache, storage_fn)

        mock_flush.assert_called_once()

    def test_skips_when_no_logs(self):
        storage_fn = _make_storage_function()
        cache = MagicMock()
        cache.get_cache.return_value = None

        with patch("dbt_ci.commands.finalize.upload.logger") as mock_logger:
            upload_logs("gs://bucket/path", cache, storage_fn)

        storage_fn.assert_not_called()
        mock_logger.warning.assert_called_once()
