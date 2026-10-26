"""Unit tests for the init command."""

import pytest
from unittest.mock import MagicMock, patch
from argparse import Namespace
from dbt_ci.commands.init.index import (
    init as index,
)


class TestInitCommand:
    """Test the init command."""

    @patch("dbt_ci.commands.init.index.CacheManager")
    @patch("dbt_ci.commands.init.index.init_storage_connector")
    @patch("dbt_ci.commands.init.index.DbtCommands")
    @patch("dbt_ci.commands.init.index.StateModified")
    @patch("dbt_ci.commands.init.index.get_manifest_file")
    @patch("dbt_ci.commands.init.index.click.secho")
    def test_init_success_no_modified_nodes(
        self,
        mock_secho,
        mock_get_manifest,
        mock_dbt_state,
        mock_dbt_commands,
        mock_storage,
        mock_cache,
    ):
        """Test successful init with no modified nodes."""
        # Setup mocks
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance
        mock_storage.return_value = None

        # Simulate StateModified.get_state_modified finding no modified nodes and exiting
        mock_dbt_state.return_value.get_state_modified.side_effect = SystemExit(0)

        # Mock DbtGraph

        # Mock manifest file
        mock_get_manifest.return_value = {"metadata": {}}

        # Run init - expect SystemExit(0)
        args = Namespace(
            dbt_project_dir="/dbt",
            reference_state="/dbt/.dbtstate",
            reference_vars=None,
            dry_run=False,
        )
        with pytest.raises(SystemExit) as exc_info:
            index(args)

        # Verify reference compile was called before state check
        mock_dbt_commands.return_value.reference_compile.assert_called_once()

        # Verify exit code
        assert exc_info.value.code == 0

    @patch("dbt_ci.commands.init.index.CacheManager")
    @patch("dbt_ci.commands.init.index.init_storage_connector")
    @patch("dbt_ci.commands.init.index.DbtCommands")
    @patch("dbt_ci.commands.init.index.StateModified")
    @patch("dbt_ci.commands.init.index.get_manifest_file")
    @patch("dbt_ci.commands.init.index.click.secho")
    @patch("dbt_ci.commands.init.index.init_summary")
    def test_init_success_with_modified_nodes(
        self,
        mock_init_summary,
        mock_secho,
        mock_get_manifest,
        mock_dbt_state,
        mock_dbt_commands,
        mock_storage,
        mock_cache,
    ):
        """Test successful init with modified nodes."""
        # Setup mocks
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance
        mock_storage.return_value = None

        # Mock StateModified.get_state_modified to return a StateChangeSummary
        mock_dbt_state.return_value.get_state_modified.return_value = {
            "modified_nodes": {
                "model": {"model.project.model1": {"name": "model1", "resource_type": "model"}}
            },
            "deleted_nodes": {},
            "new_nodes": {},
        }

        mock_get_manifest.return_value = {"metadata": {}}

        # Run init - should complete successfully without raising SystemExit
        args = Namespace(
            dbt_project_dir="/dbt",
            reference_state="/dbt/.dbtstate",
            reference_target="prod",
            reference_vars=None,
            skip_target_compile=False,
            dry_run=False,
        )
        index(args)

        # Verify cache was written
        assert mock_cache_instance.write_cache.call_count >= 1

        # Verify dbt_command_reference_compile was called
        mock_dbt_commands.return_value.reference_compile.assert_called_once()

        # Verify state modified was called
        mock_dbt_state.return_value.get_state_modified.assert_called_once()

    @patch("dbt_ci.commands.init.index.CacheManager")
    @patch("dbt_ci.commands.init.index.click.secho")
    def test_init_error_handling(self, mock_secho, mock_cache):
        """Test init error handling."""
        # Setup mocks to raise an exception during initialization
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.side_effect = Exception("Configuration error")
        mock_cache.return_value = mock_cache_instance

        # Run init - expect SystemExit(1)
        args = Namespace(
            dbt_project_dir="/dbt", reference_vars=None, skip_target_compile=False, dry_run=False
        )
        with pytest.raises(SystemExit) as exc_info:
            index(args)

        # Verify exit was called with error code
        assert exc_info.value.code == 1

    @patch("dbt_ci.commands.init.index.CacheManager")
    @patch("dbt_ci.commands.init.index.init_storage_connector")
    @patch("dbt_ci.commands.init.index.DbtCommands")
    @patch("dbt_ci.commands.init.index.StateModified")
    @patch("dbt_ci.commands.init.index.get_manifest_file")
    @patch("dbt_ci.commands.init.index.click.secho")
    def test_init_with_reference_target(
        self,
        mock_secho,
        mock_get_manifest,
        mock_dbt_state,
        mock_dbt_commands,
        mock_storage,
        mock_cache,
    ):
        """Test init with reference target specified."""
        # Setup mocks
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance
        mock_storage.return_value = None

        # Simulate StateModified.get_state_modified finding no modified nodes and exiting
        mock_dbt_state.return_value.get_state_modified.side_effect = SystemExit(0)

        # Mock DbtGraph

        # Mock manifest file
        mock_get_manifest.return_value = {"metadata": {}}

        # Run init - expect SystemExit(0)
        args = Namespace(
            dbt_project_dir="/dbt",
            reference_state="/dbt/.dbtstate",
            reference_target="prod",
            reference_vars=None,
            skip_target_compile=False,
            dry_run=False,
        )
        with pytest.raises(SystemExit) as exc_info:
            index(args)

        # Verify reference compile was called with reference target internally
        mock_dbt_commands.return_value.reference_compile.assert_called_once()

        # Verify exit code
        assert exc_info.value.code == 0


class TestResolveManifestFromStorage:
    """Test the resolve_manifest_file_from_storage helper function."""

    @patch("builtins.open", new_callable=MagicMock)
    @patch("dbt_ci.commands.init.resolve_manifest.Path")
    @patch("dbt_ci.commands.init.resolve_manifest.logger")
    def test_resolve_manifest_creates_directory(self, mock_logger, mock_path, mock_open):
        """Test that the function creates the necessary directory."""
        from dbt_ci.commands.init.resolve_manifest import resolve_manifest_file_from_storage

        # Setup mocks
        storage_connector = {"download": MagicMock(return_value={"metadata": {}})}
        state_uri = "s3://bucket/path"
        variables = Namespace(
            reference_state="dbt/.dbtstate",
            dbt_project_dir="dbt",
            state="dbt/.dbtstate",
            runner="local",
        )

        # Mock Path operations
        mock_path_instance = MagicMock()
        mock_path.return_value = mock_path_instance
        mock_path.cwd.return_value = mock_path_instance

        # Run function
        resolve_manifest_file_from_storage((storage_connector, state_uri), variables)

        # Verify download was called
        storage_connector["download"].assert_called_once_with(state_uri)


class TestReferenceManifestCaching:
    """Test that init preserves the reference baseline it compared against.

    The reference *target* (which warehouse profile to compile against) is independent
    of the reference *state* (the baseline to diff against). Conflating them overwrote
    the cached baseline with the target manifest, which left `delete` unable to look up
    the nodes it was supposed to drop.
    """

    def _args(self, tmp_path, **overrides):
        """Build an init args namespace pointing at a local state directory."""
        defaults = {
            "dbt_project_dir": str(tmp_path),
            "reference_state": str(tmp_path / "state"),
            "reference_target": None,
            "target": "dev",
            "state_uri": None,
            "comparison_strategy": "dbt",
            "runner": "dbt",
            "reference_path": "reference",
        }
        defaults.update(overrides)
        return Namespace(**defaults)

    @patch("dbt_ci.commands.init.index.init_summary")
    @patch("dbt_ci.commands.init.index.StateModified")
    @patch("dbt_ci.commands.init.index.DbtCommands")
    @patch("dbt_ci.commands.init.index.get_manifest_file")
    @patch("dbt_ci.commands.init.index.get_reference_manifest_file")
    @patch("dbt_ci.commands.init.index.CacheManager")
    @patch("dbt_ci.commands.init.index.click.secho")
    def test_local_state_is_cached_as_the_reference(
        self,
        _secho,
        mock_cache,
        mock_ref_manifest,
        mock_target_manifest,
        _dbt_commands,
        mock_state_modified,
        _summary,
        tmp_path,
    ):
        """A --state directory is cached as the baseline, not discarded."""
        mock_cache.return_value.get_cache.return_value = {"nodes": {}}
        mock_ref_manifest.return_value = {"nodes": {"model.p.gone": {}}}
        mock_target_manifest.return_value = {"nodes": {}}
        mock_state_modified.return_value.get_state_modified.return_value = {}

        index(self._args(tmp_path))

        # The baseline is written from the state directory...
        mock_cache.return_value.write_reference_manifest.assert_called_once_with(
            {"nodes": {"model.p.gone": {}}}
        )
        # ...and is not replaced by the target manifest afterwards.
        assert mock_cache.return_value.write_reference_manifest.call_count == 1

    @patch("dbt_ci.commands.init.index.init_summary")
    @patch("dbt_ci.commands.init.index.StateModified")
    @patch("dbt_ci.commands.init.index.DbtCommands")
    @patch("dbt_ci.commands.init.index.get_manifest_file")
    @patch("dbt_ci.commands.init.index.get_reference_manifest_file")
    @patch("dbt_ci.commands.init.index.CacheManager")
    @patch("dbt_ci.commands.init.index.click.secho")
    def test_target_manifest_used_when_no_baseline_exists(
        self,
        _secho,
        mock_cache,
        mock_ref_manifest,
        mock_target_manifest,
        _dbt_commands,
        mock_state_modified,
        _summary,
        tmp_path,
    ):
        """With no reference state at all, the target manifest stands in as the baseline."""
        mock_cache.return_value.get_cache.return_value = None
        mock_ref_manifest.side_effect = FileNotFoundError("no manifest")
        mock_target_manifest.return_value = {"nodes": {"model.p.a": {}}}
        mock_state_modified.return_value.get_state_modified.return_value = {}

        index(self._args(tmp_path))

        mock_cache.return_value.write_reference_manifest.assert_called_once_with(
            {"nodes": {"model.p.a": {}}}
        )

    @patch("dbt_ci.commands.init.index.init_summary")
    @patch("dbt_ci.commands.init.index.StateModified")
    @patch("dbt_ci.commands.init.index.DbtCommands")
    @patch("dbt_ci.commands.init.index.get_manifest_file")
    @patch("dbt_ci.commands.init.index.get_reference_manifest_file")
    @patch("dbt_ci.commands.init.index.CacheManager")
    @patch("dbt_ci.commands.init.index.click.secho")
    def test_missing_state_does_not_abort_init(
        self,
        _secho,
        mock_cache,
        mock_ref_manifest,
        mock_target_manifest,
        _dbt_commands,
        mock_state_modified,
        _summary,
        tmp_path,
    ):
        """Caching the baseline is best-effort; a missing file must not fail init."""
        mock_cache.return_value.get_cache.return_value = {"already": "cached"}
        mock_ref_manifest.side_effect = FileNotFoundError("no manifest")
        mock_target_manifest.return_value = {"nodes": {}}
        mock_state_modified.return_value.get_state_modified.return_value = {}

        index(self._args(tmp_path))

        mock_state_modified.return_value.get_state_modified.assert_called_once()
