"""Unit tests for finalize upload logic."""

import pytest
from unittest.mock import MagicMock, patch
from argparse import Namespace
from dbt_ci.commands.finalize.upload import (
    finalize_upload_files,
    upload_cache,
    upload_logs,
    upload_manifest,
)
from dbt_ci.errors import DbtCiError
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
        with (
            patch("dbt_ci.commands.finalize.upload.CacheManager"),
            patch("dbt_ci.commands.finalize.upload.init_storage_connector") as mock_storage,
        ):
            assert finalize_upload_files(args) == {"uploaded": [], "skipped": "no --artifacts-uri"}
            mock_storage.assert_not_called()

    def test_skips_when_no_files(self):
        """Upload should be skipped (with info log) when files list is empty."""
        args = _make_args(artifacts_uri="gs://bucket/path", files=())
        mock_connector = MagicMock()
        mock_connector.get.return_value = _make_storage_function()
        with (
            patch("dbt_ci.commands.finalize.upload.CacheManager"),
            patch("dbt_ci.commands.finalize.upload.init_storage_connector") as mock_init,
            patch("dbt_ci.commands.finalize.upload.logger") as mock_logger,
        ):
            mock_init.return_value = (mock_connector, "gs://bucket/path")
            assert finalize_upload_files(args)["skipped"] == "no --files"
            mock_logger.info.assert_any_call(
                "No files specified for upload. Please specify which files to upload using the "
                "--files argument. Skipping artifact upload."
            )

    def test_skips_when_no_storage_connector(self):
        """Upload should be skipped with a warning when no connector is found."""
        args = _make_args(artifacts_uri="gs://bucket/path", files=("manifest",))
        with (
            patch("dbt_ci.commands.finalize.upload.CacheManager"),
            patch("dbt_ci.commands.finalize.upload.init_storage_connector", return_value=None),
            patch("dbt_ci.commands.finalize.upload.logger") as mock_logger,
        ):
            assert finalize_upload_files(args) == {
                "artifacts_uri": "gs://bucket/path",
                "uploaded": [],
                "skipped": "no storage connector for the URI",
            }
            mock_logger.warning.assert_any_call(
                "No valid storage connector found for artifact upload. Skipping artifact upload."
            )

    def test_skips_when_no_upload_function_on_connector(self):
        """Upload should be skipped when the connector has no 'upload' key."""
        args = _make_args(artifacts_uri="gs://bucket/path", files=("manifest",))
        mock_connector = {"name": "test", "upload": None, "download": MagicMock()}
        with (
            patch("dbt_ci.commands.finalize.upload.CacheManager"),
            patch(
                "dbt_ci.commands.finalize.upload.init_storage_connector",
                return_value=(mock_connector, "gs://bucket/path"),
            ),
            patch("dbt_ci.commands.finalize.upload.logger") as mock_logger,
        ):
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
        with (
            patch("dbt_ci.commands.finalize.upload.CacheManager") as mock_cm,
            patch(
                "dbt_ci.commands.finalize.upload.init_storage_connector",
                return_value=(mock_connector, "gs://bucket/path"),
            ),
            patch.dict(
                "dbt_ci.commands.finalize.upload.UPLOAD_MAPPING", {"manifest": mock_upload_manifest}
            ),
        ):
            summary = finalize_upload_files(args)
            uri, cache, recorder = mock_upload_manifest.call_args.args
            assert (uri, cache) == ("gs://bucket/path", mock_cm.return_value)
            # The function handed on uploads through the connector and records the URI
            recorder("gs://bucket/path/x.json", {}, "application/json")
            mock_storage_fn.assert_called_once_with(
                "gs://bucket/path/x.json", {}, "application/json"
            )
            assert summary == {
                "artifacts_uri": "gs://bucket/path",
                "uploaded": ["gs://bucket/path/x.json"],
            }

    def test_calls_correct_upload_function_for_cache(self):
        """upload_cache should be called when 'cache' is in files."""
        args = _make_args(artifacts_uri="s3://bucket/path", files=("cache",))
        mock_storage_fn = _make_storage_function()
        mock_connector = {"name": "S3", "upload": mock_storage_fn, "download": MagicMock()}
        mock_upload_cache = MagicMock()
        with (
            patch("dbt_ci.commands.finalize.upload.CacheManager") as mock_cm,
            patch(
                "dbt_ci.commands.finalize.upload.init_storage_connector",
                return_value=(mock_connector, "s3://bucket/path"),
            ),
            patch.dict(
                "dbt_ci.commands.finalize.upload.UPLOAD_MAPPING", {"cache": mock_upload_cache}
            ),
        ):
            summary = finalize_upload_files(args)
            uri, cache, recorder = mock_upload_cache.call_args.args
            assert (uri, cache) == ("s3://bucket/path", mock_cm.return_value)
            # The function handed on uploads through the connector and records the URI
            recorder("s3://bucket/path/x.json", {}, "application/json")
            mock_storage_fn.assert_called_once_with(
                "s3://bucket/path/x.json", {}, "application/json"
            )
            assert summary == {
                "artifacts_uri": "s3://bucket/path",
                "uploaded": ["s3://bucket/path/x.json"],
            }

    def test_calls_correct_upload_function_for_logs(self):
        """upload_logs should be called when 'log' is in files."""
        args = _make_args(artifacts_uri="gs://bucket/path", files=("log",))
        mock_storage_fn = _make_storage_function()
        mock_connector = {"name": "GCS", "upload": mock_storage_fn, "download": MagicMock()}
        mock_upload_logs = MagicMock()
        with (
            patch("dbt_ci.commands.finalize.upload.CacheManager") as mock_cm,
            patch(
                "dbt_ci.commands.finalize.upload.init_storage_connector",
                return_value=(mock_connector, "gs://bucket/path"),
            ),
            patch.dict("dbt_ci.commands.finalize.upload.UPLOAD_MAPPING", {"log": mock_upload_logs}),
        ):
            summary = finalize_upload_files(args)
            uri, cache, recorder = mock_upload_logs.call_args.args
            assert (uri, cache) == ("gs://bucket/path", mock_cm.return_value)
            # The function handed on uploads through the connector and records the URI
            recorder("gs://bucket/path/x.json", {}, "application/json")
            mock_storage_fn.assert_called_once_with(
                "gs://bucket/path/x.json", {}, "application/json"
            )
            assert summary == {
                "artifacts_uri": "gs://bucket/path",
                "uploaded": ["gs://bucket/path/x.json"],
            }

    def test_calls_multiple_upload_functions(self):
        """Both upload functions are called when multiple file types are requested."""
        args = _make_args(artifacts_uri="gs://bucket/path", files=("manifest", "cache"))
        mock_storage_fn = _make_storage_function()
        mock_connector = {"name": "GCS", "upload": mock_storage_fn, "download": MagicMock()}
        mock_upload_manifest = MagicMock()
        mock_upload_cache = MagicMock()
        with (
            patch("dbt_ci.commands.finalize.upload.CacheManager"),
            patch(
                "dbt_ci.commands.finalize.upload.init_storage_connector",
                return_value=(mock_connector, "gs://bucket/path"),
            ),
            patch.dict(
                "dbt_ci.commands.finalize.upload.UPLOAD_MAPPING",
                {"manifest": mock_upload_manifest, "cache": mock_upload_cache},
            ),
        ):
            finalize_upload_files(args)
            mock_upload_manifest.assert_called_once()
            mock_upload_cache.assert_called_once()

    def test_unknown_file_type_skipped_with_warning(self):
        """An unknown file type should be skipped and a warning logged."""
        args = _make_args(artifacts_uri="gs://bucket/path", files=("unknown_type",))
        mock_storage_fn = _make_storage_function()
        mock_connector = {"name": "GCS", "upload": mock_storage_fn, "download": MagicMock()}
        with (
            patch("dbt_ci.commands.finalize.upload.CacheManager"),
            patch(
                "dbt_ci.commands.finalize.upload.init_storage_connector",
                return_value=(mock_connector, "gs://bucket/path"),
            ),
            patch("dbt_ci.commands.finalize.upload.logger") as mock_logger,
        ):
            finalize_upload_files(args)
            mock_logger.warning.assert_any_call(
                "No upload function found for file type 'unknown_type'. Skipping upload for this "
                "file type."
            )
            mock_storage_fn.assert_not_called()

    def test_unknown_file_type_does_not_block_valid_types(self):
        """A valid file type should still be uploaded even if a preceding type is unknown."""
        args = _make_args(artifacts_uri="gs://bucket/path", files=("unknown_type", "manifest"))
        mock_storage_fn = _make_storage_function()
        mock_connector = {"name": "GCS", "upload": mock_storage_fn, "download": MagicMock()}
        mock_upload_manifest = MagicMock()
        with (
            patch("dbt_ci.commands.finalize.upload.CacheManager"),
            patch(
                "dbt_ci.commands.finalize.upload.init_storage_connector",
                return_value=(mock_connector, "gs://bucket/path"),
            ),
            patch.dict(
                "dbt_ci.commands.finalize.upload.UPLOAD_MAPPING", {"manifest": mock_upload_manifest}
            ),
        ):
            finalize_upload_files(args)
            mock_upload_manifest.assert_called_once()


# ---------------------------------------------------------------------------
# Individual upload helpers
# ---------------------------------------------------------------------------


class TestUploadManifest:

    @pytest.fixture(autouse=True)
    def no_commit(self):
        """Which manifest is uploaded is tested without the per-commit copy (see test_baseline)."""
        with patch("dbt_ci.commands.finalize.upload.current_commit_sha", return_value=None):
            yield

    def test_uploads_target_manifest_when_present(self):
        storage_fn = _make_storage_function()
        cache = MagicMock()
        cache.get_cache.side_effect = lambda name=None: (
            {"key": "value"} if name == "target_manifest.json" else None
        )

        upload_manifest("gs://bucket/path", cache, storage_fn)

        storage_fn.assert_any_call(
            "gs://bucket/path/manifest.json", {"key": "value"}, "application/json"
        )

    def test_falls_back_to_reference_manifest(self):
        storage_fn = _make_storage_function()
        cache = MagicMock()
        cache.get_cache.side_effect = lambda name=None: (
            None if name == "target_manifest.json" else {"ref": "data"}
        )

        upload_manifest("gs://bucket/path", cache, storage_fn)

        storage_fn.assert_any_call(
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
        cache.get_cache_text.return_value = "some log content"

        upload_logs("gs://bucket/path", cache, storage_fn)

        storage_fn.assert_called_once_with(
            "gs://bucket/path/logs.txt", "some log content", "text/plain"
        )

    def test_reads_the_file_the_logger_actually_writes(self):
        """The log handler writes dbt-ci.log, so reading any other name uploads nothing."""
        storage_fn = _make_storage_function()
        cache = MagicMock()
        cache.get_cache_text.return_value = "some log content"

        upload_logs("gs://bucket/path", cache, storage_fn)

        cache.get_cache_text.assert_called_once_with(LOG_FILE_NAME)

    def test_flushes_buffered_records_before_reading(self):
        """Records still buffered by the handler would otherwise be missing."""
        storage_fn = _make_storage_function()
        cache = MagicMock()
        cache.get_cache_text.return_value = "some log content"

        with patch("dbt_ci.commands.finalize.upload.flush_log_file") as mock_flush:
            upload_logs("gs://bucket/path", cache, storage_fn)

        mock_flush.assert_called_once()

    def test_skips_when_no_logs(self):
        storage_fn = _make_storage_function()
        cache = MagicMock()
        cache.get_cache_text.return_value = None

        with patch("dbt_ci.commands.finalize.upload.logger") as mock_logger:
            upload_logs("gs://bucket/path", cache, storage_fn)

        storage_fn.assert_not_called()
        mock_logger.warning.assert_called_once()


class TestArtifactsUri:

    def test_trailing_slash_is_stripped(self):
        """A trailing slash must not produce a double-slash object key."""
        args = _make_args(artifacts_uri="gs://bucket/path/", files=("manifest",))
        mock_connector = {"name": "GCS", "upload": MagicMock(), "download": MagicMock()}
        mock_upload_manifest = MagicMock()
        with (
            patch("dbt_ci.commands.finalize.upload.CacheManager"),
            patch(
                "dbt_ci.commands.finalize.upload.init_storage_connector",
                return_value=(mock_connector, "gs://bucket/path/"),
            ),
            patch.dict(
                "dbt_ci.commands.finalize.upload.UPLOAD_MAPPING", {"manifest": mock_upload_manifest}
            ),
        ):
            finalize_upload_files(args)
        assert mock_upload_manifest.call_args[0][0] == "gs://bucket/path"


# ---------------------------------------------------------------------------
# finalize command — dry run and ephemeral cleanup
# ---------------------------------------------------------------------------


class TestFinalizeDryRun:

    def test_dry_run_skips_upload_and_keeps_cache(self):
        """A dry run must neither upload artifacts nor clear the cache."""
        from dbt_ci.commands.finalize.index import finalize

        args = _make_args(
            artifacts_uri="gs://bucket/prod-state", dry_run=True, clean_ephemeral=False
        )
        with (
            patch("dbt_ci.commands.finalize.index.CacheManager") as mock_cm,
            patch("dbt_ci.commands.finalize.index.finalize_upload_files") as mock_upload,
            patch("dbt_ci.commands.finalize.index.click.secho"),
            pytest.raises(SystemExit) as exc_info,
        ):
            finalize(args)

        assert exc_info.value.code == 0
        mock_upload.assert_not_called()
        mock_cm.return_value.clear_cache.assert_not_called()

    def test_dry_run_records_what_it_would_upload(self):
        """The report entry of a dry run names the files and where they would have gone."""
        from dbt_ci.commands.finalize.index import finalize

        args = _make_args(
            artifacts_uri="gs://bucket/prod-state",
            files=("manifest", "log"),
            dry_run=True,
            clean_ephemeral=False,
        )
        with (
            patch("dbt_ci.commands.finalize.index.CacheManager") as mock_cm,
            patch("dbt_ci.commands.finalize.index.finalize_upload_files"),
            patch("dbt_ci.commands.finalize.index.click.secho"),
            pytest.raises(SystemExit),
        ):
            finalize(args)
        mock_cm.return_value.update_report.assert_called_with(
            "finalize",
            "completed",
            {
                "artifacts_uri": "gs://bucket/prod-state",
                "uploaded": [],
                "skipped": "dry run",
                "files": ["manifest", "log"],
            },
        )

    def test_dry_run_cleanup_needs_no_client(self):
        """A dry-run cleanup lists datasets without creating a warehouse client."""
        cleanup = TestCleanUpEphemeral()
        client_factory, delete_datasets, _ = cleanup.run_cleanup(
            cleanup._map(("ci_pr_1", None)), [], dry_run=True
        )
        client_factory.assert_not_called()
        delete_datasets.assert_called_once_with(None, {"proj.ci_pr_1"}, True, 2)


class TestCleanUpEphemeral:

    @staticmethod
    def _map(*datasets: tuple[str, str | None]) -> dict:
        """Build an ephemeral map with one node per (ephemeral schema, reference schema) pair."""
        return {
            f"model.pkg.m{i}": {
                "name": f"m{i}",
                "resource_type": "model",
                "ephemeral_config": {
                    "database": "proj",
                    "schema": schema,
                    "name": f"m{i}",
                    "alias": None,
                },
                "reference_config": (
                    {"database": "proj", "schema": ref_schema, "name": f"m{i}", "alias": None}
                    if ref_schema
                    else None
                ),
            }
            for i, (schema, ref_schema) in enumerate(datasets)
        }

    def run_cleanup(
        self,
        ephemeral_map: dict,
        reference_schemas: list[str],
        delete_side_effect=None,
        dry_run=False,
    ):
        """Run clean_up_ephemeral with stubbed connector and reference graph."""
        from dbt_ci.commands.ephemeral.destroy import clean_up_ephemeral

        client_factory = MagicMock()
        delete_datasets = MagicMock(side_effect=delete_side_effect)
        connector = {"client": client_factory, "methods": {"delete_datasets": delete_datasets}}
        reference_graph = {
            "source": {
                f"source.pkg.raw.{s}": {"database": "proj", "schema": s} for s in reference_schemas
            }
        }
        cache = MagicMock()
        cache.get_cache.return_value = ephemeral_map
        args = _make_args(dry_run=dry_run)
        with (
            patch(
                "dbt_ci.commands.ephemeral.destroy.get_profile",
                return_value={"type": "bigquery", "threads": 2},
            ),
            patch("dbt_ci.commands.ephemeral.destroy.get_connector", return_value=connector),
            patch("dbt_ci.commands.ephemeral.destroy.DbtGraph") as mock_graph,
        ):
            mock_graph.return_value.to_dict.return_value = reference_graph
            clean_up_ephemeral(args, cache)
        return client_factory, delete_datasets, args

    def test_deletes_ci_datasets_with_a_real_client(self):
        """The connector's client factory is called and its client is used for deletion."""
        client_factory, delete_datasets, args = self.run_cleanup(
            self._map(("ci_pr_1", "analytics")), []
        )
        client_factory.assert_called_once_with(args)
        delete_datasets.assert_called_once_with(
            client_factory.return_value, {"proj.ci_pr_1"}, False, 2
        )

    def test_refuses_production_datasets(self):
        """Datasets used by the reference manifest are never deleted."""
        ephemeral_map = self._map(
            ("ci_pr_1", "analytics"), ("analytics", "analytics"), ("raw", None)
        )
        _, delete_datasets, _ = self.run_cleanup(ephemeral_map, ["raw"])
        assert delete_datasets.call_args[0][1] == {"proj.ci_pr_1"}

    def test_nothing_left_skips_deletion(self):
        """When every dataset is protected, nothing is deleted."""
        _, delete_datasets, _ = self.run_cleanup(self._map(("analytics", "analytics")), [])
        delete_datasets.assert_not_called()

    def test_missing_reference_manifest_refuses_cleanup(self):
        """Without the production manifest nothing can be protected, so nothing is deleted."""
        from dbt_ci.commands.ephemeral.destroy import clean_up_ephemeral

        cache = MagicMock()
        cache.get_cache.side_effect = lambda name="cache.json", *_: (
            self._map(("ci_pr_1", None)) if name == "ephemeral_map.json" else None
        )
        connector = {"client": MagicMock(), "methods": {"delete_datasets": MagicMock()}}
        with (
            patch(
                "dbt_ci.commands.ephemeral.destroy.get_profile", return_value={"type": "bigquery"}
            ),
            patch("dbt_ci.commands.ephemeral.destroy.get_connector", return_value=connector),
            pytest.raises(DbtCiError, match="No reference manifest"),
        ):
            clean_up_ephemeral(_make_args(dry_run=False), cache)
        connector["methods"]["delete_datasets"].assert_not_called()

    def test_errors_propagate(self):
        """A failed cleanup must fail finalize instead of being logged and ignored."""
        with pytest.raises(RuntimeError):
            self.run_cleanup(
                self._map(("ci_pr_1", None)), [], delete_side_effect=RuntimeError("boom")
            )


class TestFinalizeCleanupOrder:
    """The ephemeral teardown must not depend on the manifest or the artifact upload."""

    @staticmethod
    def run_finalize(manifest=None, upload_side_effect=None, cleanup_side_effect=None):
        """Run finalize with --clean-ephemeral, returning the exit code and the mocks."""
        from dbt_ci.commands.finalize.index import finalize

        calls: list[str] = []
        args = _make_args(
            artifacts_uri="gs://bucket/prod-state", dry_run=False, clean_ephemeral=True
        )

        def cleanup(*_):
            calls.append("cleanup")
            if cleanup_side_effect:
                raise cleanup_side_effect

        def upload(*_):
            calls.append("upload")
            if upload_side_effect:
                raise upload_side_effect
            return {"artifacts_uri": "gs://bucket/prod-state", "uploaded": []}

        with (
            patch("dbt_ci.commands.finalize.index.CacheManager") as mock_cm,
            patch("dbt_ci.commands.finalize.index.finalize_upload_files", side_effect=upload),
            patch("dbt_ci.commands.finalize.index.clean_up_ephemeral", side_effect=cleanup),
            patch("dbt_ci.commands.finalize.index.print_exception"),
            patch("dbt_ci.commands.finalize.index.click.secho"),
            pytest.raises(SystemExit) as exc_info,
        ):
            mock_cm.return_value.get_cache.side_effect = lambda name="cache.json", *_: (
                manifest if name in ("target_manifest.json", "reference_manifest.json") else {}
            )
            finalize(args)
        return exc_info.value.code, calls, mock_cm.return_value

    def test_cleans_up_before_uploading(self):
        """Teardown runs first, then the upload, and the cache is cleared on success."""
        code, calls, cache = self.run_finalize(manifest={"nodes": {}})
        assert code == 0
        assert calls == ["cleanup", "upload"]
        cache.clear_cache.assert_called_once()

    def test_report_records_the_upload_not_the_cache(self):
        """finalize's report entry is the upload summary, not a copy of cache.json."""
        _, _, cache = self.run_finalize(manifest={"nodes": {}})
        cache.update_report.assert_called_with(
            "finalize",
            "completed",
            {"artifacts_uri": "gs://bucket/prod-state", "uploaded": [], "files": ["manifest"]},
        )

    def test_cleans_up_without_a_manifest(self):
        """A missing manifest still fails finalize, but only after the teardown ran."""
        code, calls, _ = self.run_finalize(manifest=None)
        assert code == 1
        assert calls == ["cleanup"]

    def test_failed_upload_does_not_skip_cleanup(self):
        """An upload that exits the process happens after the teardown."""
        code, calls, _ = self.run_finalize(manifest={"nodes": {}}, upload_side_effect=SystemExit(1))
        assert code == 1
        assert calls == ["cleanup", "upload"]

    def test_failed_cleanup_still_uploads_and_fails(self):
        """A failed teardown doesn't block the upload, fails the step and keeps the cache."""
        code, calls, cache = self.run_finalize(
            manifest={"nodes": {}}, cleanup_side_effect=RuntimeError("boom")
        )
        assert code == 1
        assert calls == ["cleanup", "upload"]
        cache.clear_cache.assert_not_called()
        cache.update_report.assert_called_with(
            "finalize", "failed", comment="Ephemeral cleanup failed: boom"
        )


class TestPullRequestGuard:
    """A pull request must not publish over the production state init reads."""

    PR = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "pull_request"}

    def check(self, monkeypatch, artifacts_uri, env=None, **args):
        """Return whether the guard stops an upload, with the given CI variables."""
        from dbt_ci.commands.finalize.upload import publishes_pull_request_over_production

        for key in ("GITHUB_ACTIONS", "GITHUB_EVENT_NAME", "GITLAB_CI", "DBT_CI_EVENT"):
            monkeypatch.delenv(key, raising=False)
        for key, value in (env or {}).items():
            monkeypatch.setenv(key, value)
        namespace = Namespace(**{"state_uri": "gs://b/dbt-state/manifest.json", **args})
        with patch("dbt_ci.commands.finalize.upload.get_cached_value", return_value=None):
            return publishes_pull_request_over_production(namespace, artifacts_uri)

    def test_pull_request_to_the_state_location_is_stopped(self, monkeypatch):
        """Same folder as the state, on a pull request: stopped."""
        assert self.check(monkeypatch, "gs://b/dbt-state", self.PR)
        assert self.check(monkeypatch, "gs://b/dbt-state/", self.PR)

    def test_other_cases_upload(self, monkeypatch):
        """Another folder, another event, no known state, or --force-manifest: uploaded."""
        assert not self.check(monkeypatch, "gs://b/prs", self.PR)
        assert not self.check(monkeypatch, "gs://b/dbt-state", {})
        assert not self.check(monkeypatch, "gs://b/dbt-state", {"DBT_CI_EVENT": "push"})
        assert not self.check(monkeypatch, "gs://b/dbt-state", {"DBT_CI_EVENT": "schedule"})
        schedule = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "schedule"}
        assert not self.check(monkeypatch, "gs://b/dbt-state", schedule)
        assert not self.check(monkeypatch, "gs://b/dbt-state", self.PR, state_uri=None)
        assert not self.check(monkeypatch, "gs://b/dbt-state", self.PR, force_manifest=True)
        assert self.check(monkeypatch, "gs://b/dbt-state", {}, event="pull-request")

    def test_state_uri_recorded_by_init(self, monkeypatch):
        """finalize reads the state URI init recorded when it wasn't given one."""
        from dbt_ci.commands.finalize.upload import publishes_pull_request_over_production

        monkeypatch.setenv("DBT_CI_EVENT", "pull-request")
        recorded = {"reference_state_uri": "s3://b/state/manifest.json", "base_ref": None}
        with patch(
            "dbt_ci.commands.finalize.upload.get_cached_value",
            side_effect=lambda _args, key: recorded.get(key),
        ):
            assert publishes_pull_request_over_production(Namespace(), "s3://b/state/")

    def test_upload_is_skipped_with_a_warning(self, monkeypatch, caplog):
        """finalize_upload_files uploads nothing and says how to fix it."""
        monkeypatch.setenv("DBT_CI_EVENT", "pull-request")
        storage = MagicMock()
        args = _make_args(
            artifacts_uri="gs://b/dbt-state/", state_uri="gs://b/dbt-state/manifest.json"
        )
        with (
            patch("dbt_ci.commands.finalize.upload.CacheManager"),
            patch(
                "dbt_ci.commands.finalize.upload.init_storage_connector",
                return_value=({"upload": storage}, "gs://b/dbt-state"),
            ),
        ):
            summary = finalize_upload_files(args)
        storage.assert_not_called()
        assert "this run is for a pull request" in caplog.text
        assert summary["skipped"] == "pull request would publish over the production state"
        assert summary["uploaded"] == []


class TestArtifactsUriPlaceholders:
    """{pr} and {branch} in --artifacts-uri give every pull request its own folder."""

    CI_VARS = (
        "GITHUB_ACTIONS",
        "GITHUB_EVENT_NAME",
        "GITHUB_EVENT_PATH",
        "GITHUB_REF",
        "GITHUB_HEAD_REF",
        "GITLAB_CI",
        "TF_BUILD",
        "BITBUCKET_BUILD_NUMBER",
        "CIRCLECI",
        "BUILDKITE",
        "JENKINS_URL",
        "DBT_CI_EVENT",
    )
    PR = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_REF": "refs/pull/42/merge",
        "GITHUB_HEAD_REF": "feature/new-model",
    }

    @pytest.fixture(autouse=True)
    def ci_env(self, monkeypatch):
        """Start every test outside CI, on a detached HEAD, and return a setter."""
        for key in self.CI_VARS:
            monkeypatch.delenv(key, raising=False)
        with patch("dbt_ci.utilities.ci_event._git_current_branch", return_value=None):
            yield lambda env: [monkeypatch.setenv(k, v) for k, v in env.items()]

    def upload(self, **args):
        """Run finalize_upload_files with a mocked connector; return the upload mock."""
        mock_upload_manifest = MagicMock()
        connector = {"name": "GCS", "upload": MagicMock(), "download": MagicMock()}
        with (
            patch("dbt_ci.commands.finalize.upload.CacheManager"),
            patch("dbt_ci.commands.finalize.upload.get_cached_value", return_value=None),
            patch(
                "dbt_ci.commands.finalize.upload.init_storage_connector",
                side_effect=lambda uri: (connector, uri),
            ) as init_storage,
            patch.dict(
                "dbt_ci.commands.finalize.upload.UPLOAD_MAPPING", {"manifest": mock_upload_manifest}
            ),
        ):
            finalize_upload_files(_make_args(**args))
        return mock_upload_manifest, init_storage

    def test_uploads_to_the_resolved_uri(self, ci_env):
        """The files go to the pull request's folder, never a literal {pr}."""
        ci_env(self.PR)
        upload, init_storage = self.upload(artifacts_uri="gs://b/prs/{pr}/{branch}/")
        init_storage.assert_called_once_with("gs://b/prs/42/feature-new-model")
        assert upload.call_args[0][0] == "gs://b/prs/42/feature-new-model"

    def test_unresolved_placeholder_uploads_nothing(self, ci_env):
        """A push has no {pr}: finalize_upload_files raises before touching storage."""
        ci_env({"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "push"})
        with pytest.raises(DbtCiError, match=r"Cannot resolve \{pr\}"):
            self.upload(artifacts_uri="gs://b/prs/{pr}/")

    def test_guard_compares_the_resolved_uri(self, ci_env):
        """A {branch} that resolves to the state folder is stopped like a literal one."""
        ci_env({**self.PR, "GITHUB_HEAD_REF": "dbt-state"})
        upload, _ = self.upload(
            artifacts_uri="gs://b/{branch}/", state_uri="gs://b/dbt-state/manifest.json"
        )
        upload.assert_not_called()

        ci_env({"GITHUB_HEAD_REF": "feature"})
        upload, _ = self.upload(
            artifacts_uri="gs://b/{branch}/", state_uri="gs://b/dbt-state/manifest.json"
        )
        upload.assert_called_once()

    def run_finalize(self, dry_run, artifacts_uri):
        """Run the finalize command; return the exit code, upload mock and resolved args."""
        from dbt_ci.commands.finalize.index import finalize

        args = _make_args(artifacts_uri=artifacts_uri, dry_run=dry_run, clean_ephemeral=False)
        with (
            patch("dbt_ci.commands.finalize.index.CacheManager") as mock_cm,
            patch("dbt_ci.commands.finalize.index.finalize_upload_files") as mock_upload,
            patch("dbt_ci.commands.finalize.index.click.secho"),
            pytest.raises(SystemExit) as exc_info,
        ):
            mock_cm.return_value.get_cache.return_value = {"nodes": {}}
            finalize(args)
        return exc_info.value.code, mock_upload, args, mock_cm.return_value

    def test_dry_run_shows_the_resolved_uri(self, ci_env, caplog):
        """A dry run says where the files would go, with the placeholders filled in."""
        ci_env(self.PR)
        with caplog.at_level("INFO"):
            code, upload, _, _ = self.run_finalize(True, "gs://b/prs/{pr}/")
        assert code == 0
        upload.assert_not_called()
        assert "skipping upload of ['manifest'] to gs://b/prs/42/." in caplog.text
        assert "Resolved --artifacts-uri gs://b/prs/{pr}/ to gs://b/prs/42/" in caplog.text

    def test_finalize_uploads_with_the_resolved_uri(self, ci_env):
        """The upload step gets the resolved URI."""
        ci_env(self.PR)
        code, upload, args, _ = self.run_finalize(False, "gs://b/prs/{pr}/")
        assert code == 0
        upload.assert_called_once_with(args)
        assert args.artifacts_uri == "gs://b/prs/42/"

    @pytest.mark.parametrize("dry_run", [True, False])
    def test_unresolved_placeholder_fails_finalize(self, ci_env, dry_run, caplog):
        """Dry run or not, an unresolvable placeholder fails the step and keeps the cache."""
        code, upload, _, cache = self.run_finalize(dry_run, "gs://b/prs/{pr}/")
        assert code == 1
        upload.assert_not_called()
        cache.clear_cache.assert_not_called()
        assert "Cannot resolve {pr} in --artifacts-uri 'gs://b/prs/{pr}/'" in caplog.text
