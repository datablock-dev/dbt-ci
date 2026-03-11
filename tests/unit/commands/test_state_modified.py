"""Unit tests for the state_modified module."""
import pytest
from unittest.mock import MagicMock, patch, call
from argparse import Namespace
from subprocess import CompletedProcess
from dbt_ci.commands.init.state_modified import (
    get_state_modified,
    git_strategy,
    hybrid_strategy,
    dbt_strategy,
    _common_state_change,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_args(**kwargs) -> Namespace:
    defaults = dict(
        comparison_strategy="dbt",
        reference_target="prod",
        reference_vars=None,
        dbt_project_dir="/dbt",
        reference_state="/dbt/.dbtstate",
    )
    defaults.update(kwargs)
    return Namespace(**defaults)


def _make_graph_dict(nodes: dict | None = None) -> dict:
    """Minimal dependency-graph structure expected by graph_utils functions."""
    return {
        "metadata": {},
        "model": nodes or {},
    }


# ---------------------------------------------------------------------------
# get_state_modified – strategy routing
# ---------------------------------------------------------------------------

class TestGetStateModified:
    """Tests for the strategy-routing function."""

    @patch("dbt_ci.commands.init.state_modified.dbt_strategy")
    def test_routes_to_dbt_strategy(self, mock_dbt):
        mock_dbt.return_value = {"modified_nodes": {}, "deleted_nodes": {}, "new_nodes": {}}
        args = _make_args(comparison_strategy="dbt")
        get_state_modified(args)
        mock_dbt.assert_called_once_with(args)

    @patch("dbt_ci.commands.init.state_modified.git_strategy")
    def test_routes_to_git_strategy(self, mock_git):
        mock_git.return_value = {"modified_nodes": {}, "deleted_nodes": {}, "new_nodes": {}}
        args = _make_args(comparison_strategy="git")
        get_state_modified(args)
        mock_git.assert_called_once_with(args)

    @patch("dbt_ci.commands.init.state_modified.hybrid_strategy")
    def test_routes_to_hybrid_strategy(self, mock_hybrid):
        mock_hybrid.return_value = {"modified_nodes": {}, "deleted_nodes": {}, "new_nodes": {}}
        args = _make_args(comparison_strategy="hybrid")
        get_state_modified(args)
        mock_hybrid.assert_called_once_with(args)

    def test_invalid_strategy_exits(self):
        args = _make_args(comparison_strategy="unknown")
        with pytest.raises(SystemExit) as exc_info:
            get_state_modified(args)
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# git_strategy
# ---------------------------------------------------------------------------

class TestGitStrategy:
    """Tests for the git-diff-based strategy."""

    def _setup_mocks(self, mock_graph_cls, target_nodes, reference_nodes, changed_files):
        target_dict = _make_graph_dict(target_nodes)
        reference_dict = _make_graph_dict(reference_nodes)

        mock_target = MagicMock()
        mock_target.to_dict.return_value = target_dict
        mock_reference = MagicMock()
        mock_reference.to_dict.return_value = reference_dict

        mock_graph_cls.side_effect = [mock_target, mock_reference]
        return target_dict, reference_dict

    @patch("dbt_ci.commands.init.state_modified.get_structured_modified_nodes")
    @patch("dbt_ci.commands.init.state_modified.get_nodes")
    @patch("dbt_ci.commands.init.state_modified.GitAdapter")
    @patch("dbt_ci.commands.init.state_modified.DbtGraph")
    def test_modified_file_maps_to_modified_node(
        self, mock_graph_cls, mock_git_cls, mock_get_nodes, mock_structured
    ):
        target_nodes = {
            "model.project.model1": {"original_file_path": "models/model1.sql"},
        }
        self._setup_mocks(mock_graph_cls, target_nodes, {}, {
            "modified": {"models/model1.sql"},
            "added": set(),
            "deleted": set(),
        })
        mock_git_cls.return_value.get_changed_files.return_value = {
            "modified": {"models/model1.sql"},
            "added": set(),
            "deleted": set(),
        }
        mock_get_nodes.return_value = {"model.project.model1": target_nodes["model.project.model1"]}
        mock_structured.return_value = {"model": {"model.project.model1": {}}}

        args = _make_args(comparison_strategy="git")
        result = git_strategy(args)

        assert result["modified_nodes"] == {"model": {"model.project.model1": {}}}

    @patch("dbt_ci.commands.init.state_modified.get_structured_modified_nodes")
    @patch("dbt_ci.commands.init.state_modified.get_nodes")
    @patch("dbt_ci.commands.init.state_modified.GitAdapter")
    @patch("dbt_ci.commands.init.state_modified.DbtGraph")
    def test_added_file_maps_to_new_node(
        self, mock_graph_cls, mock_git_cls, mock_get_nodes, mock_structured
    ):
        target_nodes = {
            "model.project.new_model": {"original_file_path": "models/new_model.sql"},
        }
        self._setup_mocks(mock_graph_cls, target_nodes, {}, {})
        mock_git_cls.return_value.get_changed_files.return_value = {
            "modified": set(),
            "added": {"models/new_model.sql"},
            "deleted": set(),
        }
        mock_get_nodes.return_value = {}
        mock_structured.return_value = {"model": {"model.project.new_model": {}}}

        args = _make_args(comparison_strategy="git")
        result = git_strategy(args)

        # new_nodes should be populated, modified_nodes empty
        assert result["new_nodes"] == {"model": {"model.project.new_model": {}}}

    @patch("dbt_ci.commands.init.state_modified.get_structured_modified_nodes")
    @patch("dbt_ci.commands.init.state_modified.get_nodes")
    @patch("dbt_ci.commands.init.state_modified.GitAdapter")
    @patch("dbt_ci.commands.init.state_modified.DbtGraph")
    def test_deleted_file_maps_to_deleted_node(
        self, mock_graph_cls, mock_git_cls, mock_get_nodes, mock_structured
    ):
        reference_nodes = {
            "model.project.old_model": {"original_file_path": "models/old_model.sql"},
        }
        self._setup_mocks(mock_graph_cls, {}, reference_nodes, {})
        mock_git_cls.return_value.get_changed_files.return_value = {
            "modified": set(),
            "added": set(),
            "deleted": {"models/old_model.sql"},
        }
        mock_get_nodes.return_value = {}
        mock_structured.return_value = {"model": {"model.project.old_model": {}}}

        args = _make_args(comparison_strategy="git")
        result = git_strategy(args)

        assert result["deleted_nodes"] == {"model": {"model.project.old_model": {}}}

    @patch("dbt_ci.commands.init.state_modified.get_structured_modified_nodes")
    @patch("dbt_ci.commands.init.state_modified.get_nodes")
    @patch("dbt_ci.commands.init.state_modified.GitAdapter")
    @patch("dbt_ci.commands.init.state_modified.DbtGraph")
    def test_no_changed_files_returns_empty(
        self, mock_graph_cls, mock_git_cls, mock_get_nodes, mock_structured
    ):
        target_nodes = {
            "model.project.model1": {"original_file_path": "models/model1.sql"},
        }
        self._setup_mocks(mock_graph_cls, target_nodes, {}, {})
        mock_git_cls.return_value.get_changed_files.return_value = {
            "modified": set(),
            "added": set(),
            "deleted": set(),
        }
        mock_get_nodes.return_value = {}
        mock_structured.return_value = {}

        args = _make_args(comparison_strategy="git")
        result = git_strategy(args)

        assert result["modified_nodes"] == {}
        assert result["new_nodes"] == {}
        assert result["deleted_nodes"] == {}

    @patch("dbt_ci.commands.init.state_modified.get_structured_modified_nodes")
    @patch("dbt_ci.commands.init.state_modified.get_nodes")
    @patch("dbt_ci.commands.init.state_modified.GitAdapter")
    @patch("dbt_ci.commands.init.state_modified.DbtGraph")
    def test_node_without_file_path_is_skipped(
        self, mock_graph_cls, mock_git_cls, mock_get_nodes, mock_structured
    ):
        target_nodes = {
            "model.project.no_path": {},  # no original_file_path
        }
        self._setup_mocks(mock_graph_cls, target_nodes, {}, {})
        mock_git_cls.return_value.get_changed_files.return_value = {
            "modified": {"models/model1.sql"},
            "added": set(),
            "deleted": set(),
        }
        mock_get_nodes.return_value = {}
        mock_structured.return_value = {}

        args = _make_args(comparison_strategy="git")
        result = git_strategy(args)

        assert result["modified_nodes"] == {}

    @patch("dbt_ci.commands.init.state_modified.GitAdapter")
    @patch("dbt_ci.commands.init.state_modified.DbtGraph")
    def test_git_adapter_exception_exits(self, mock_graph_cls, mock_git_cls):
        mock_graph_cls.return_value.to_dict.return_value = _make_graph_dict()
        mock_git_cls.return_value.get_changed_files.side_effect = RuntimeError("git error")

        args = _make_args(comparison_strategy="git")
        with pytest.raises(SystemExit) as exc_info:
            git_strategy(args)
        assert exc_info.value.code == 1

    @patch("dbt_ci.commands.init.state_modified.get_structured_modified_nodes")
    @patch("dbt_ci.commands.init.state_modified.get_nodes")
    @patch("dbt_ci.commands.init.state_modified.GitAdapter")
    @patch("dbt_ci.commands.init.state_modified.DbtGraph")
    def test_metadata_key_is_skipped(
        self, mock_graph_cls, mock_git_cls, mock_get_nodes, mock_structured
    ):
        """Ensures the metadata key in the graph dict is not iterated as nodes."""
        # Simulate a graph dict where 'metadata' contains non-node data
        target_dict = {
            "metadata": {"dbt_version": "1.7.0"},
            "model": {
                "model.project.model1": {"original_file_path": "models/model1.sql"},
            },
        }
        mock_target = MagicMock()
        mock_target.to_dict.return_value = target_dict
        mock_reference = MagicMock()
        mock_reference.to_dict.return_value = _make_graph_dict()
        mock_graph_cls.side_effect = [mock_target, mock_reference]

        mock_git_cls.return_value.get_changed_files.return_value = {
            "modified": {"models/model1.sql"},
            "added": set(),
            "deleted": set(),
        }
        mock_get_nodes.return_value = {"model.project.model1": {}}
        mock_structured.return_value = {"model": {"model.project.model1": {}}}

        args = _make_args(comparison_strategy="git")
        # Should not raise a TypeError from iterating metadata dict values as nodes
        result = git_strategy(args)
        assert result["modified_nodes"] == {"model": {"model.project.model1": {}}}


# ---------------------------------------------------------------------------
# dbt_strategy / _common_state_change
# ---------------------------------------------------------------------------

class TestDbtStrategy:
    """Tests for the dbt state:modified-based strategy."""

    def _setup_common_mocks(
        self,
        mock_graph_cls,
        mock_run_dbt,
        mock_cache_cls,
        target_nodes: dict,
        reference_nodes: dict,
        ls_stdout: str,
    ):
        target_dict = _make_graph_dict(target_nodes)
        reference_dict = _make_graph_dict(reference_nodes)

        # DbtGraph is instantiated three times inside _common_state_change + dbt_strategy
        mock_target = MagicMock()
        mock_target.to_dict.return_value = target_dict
        mock_reference = MagicMock()
        mock_reference.to_dict.return_value = reference_dict
        mock_graph_cls.side_effect = lambda *a, **kw: (
            mock_reference if kw.get("is_reference") else mock_target
        )

        mock_run_dbt.return_value = CompletedProcess(args=[], returncode=0, stdout=ls_stdout, stderr="")
        mock_cache_cls.return_value = MagicMock()

        return target_dict, reference_dict

    @patch("dbt_ci.commands.init.state_modified.get_structured_modified_nodes")
    @patch("dbt_ci.commands.init.state_modified.get_nodes")
    @patch("dbt_ci.commands.init.state_modified.get_new_nodes")
    @patch("dbt_ci.commands.init.state_modified.get_deleted_nodes")
    @patch("dbt_ci.commands.init.state_modified.resolve_dbt_commands")
    @patch("dbt_ci.commands.init.state_modified.run_dbt_command")
    @patch("dbt_ci.commands.init.state_modified.CacheManager")
    @patch("dbt_ci.commands.init.state_modified.DbtGraph")
    def test_modified_node_returned(
        self, mock_graph_cls, mock_cache_cls, mock_run_dbt, mock_resolve,
        mock_deleted, mock_new, mock_get_nodes, mock_structured
    ):
        target_nodes = {"model.project.model1": {"original_file_path": "models/model1.sql"}}
        self._setup_common_mocks(mock_graph_cls, mock_run_dbt, mock_cache_cls, target_nodes, {}, "model1")
        mock_resolve.return_value = ["ls", "--select", "state:modified"]
        mock_deleted.return_value = []
        mock_new.return_value = []
        mock_get_nodes.return_value = {"model.project.model1": {}}
        mock_structured.return_value = {"model": {"model.project.model1": {}}}

        args = _make_args(comparison_strategy="dbt")
        result = dbt_strategy(args)

        assert result["modified_nodes"] == {"model": {"model.project.model1": {}}}

    @patch("dbt_ci.commands.init.state_modified.get_structured_modified_nodes")
    @patch("dbt_ci.commands.init.state_modified.get_nodes")
    @patch("dbt_ci.commands.init.state_modified.get_new_nodes")
    @patch("dbt_ci.commands.init.state_modified.get_deleted_nodes")
    @patch("dbt_ci.commands.init.state_modified.resolve_dbt_commands")
    @patch("dbt_ci.commands.init.state_modified.run_dbt_command")
    @patch("dbt_ci.commands.init.state_modified.CacheManager")
    @patch("dbt_ci.commands.init.state_modified.DbtGraph")
    def test_new_node_separated_from_modified(
        self, mock_graph_cls, mock_cache_cls, mock_run_dbt, mock_resolve,
        mock_deleted, mock_new, mock_get_nodes, mock_structured
    ):
        """Nodes reported by dbt ls that are also in new_nodes should not appear in modified_nodes."""
        target_nodes = {"model.project.new_model": {}}
        self._setup_common_mocks(mock_graph_cls, mock_run_dbt, mock_cache_cls, target_nodes, {}, "new_model")
        mock_resolve.return_value = ["ls"]
        mock_deleted.return_value = []
        mock_new.return_value = ["model.project.new_model"]
        mock_get_nodes.return_value = {}
        mock_structured.return_value = {}

        args = _make_args(comparison_strategy="dbt")
        result = dbt_strategy(args)

        # new_model was in new_nodes, so modified_nodes should be empty
        assert result["modified_nodes"] == {}

    @patch("dbt_ci.commands.init.state_modified.resolve_dbt_commands")
    @patch("dbt_ci.commands.init.state_modified.run_dbt_command")
    @patch("dbt_ci.commands.init.state_modified.CacheManager")
    @patch("dbt_ci.commands.init.state_modified.DbtGraph")
    def test_no_ls_output_exits_zero(
        self, mock_graph_cls, mock_cache_cls, mock_run_dbt, mock_resolve
    ):
        """When dbt ls returns nothing, _common_state_change writes cache and calls sys.exit(0)."""
        self._setup_common_mocks(mock_graph_cls, mock_run_dbt, mock_cache_cls, {}, {}, "")
        mock_run_dbt.return_value = None  # triggers the "No modified nodes" branch
        mock_resolve.return_value = ["ls"]

        args = _make_args(comparison_strategy="dbt")
        with pytest.raises(SystemExit) as exc_info:
            _common_state_change(args)
        assert exc_info.value.code == 0

    @patch("dbt_ci.commands.init.state_modified.resolve_dbt_commands")
    @patch("dbt_ci.commands.init.state_modified.run_dbt_command")
    @patch("dbt_ci.commands.init.state_modified.CacheManager")
    @patch("dbt_ci.commands.init.state_modified.DbtGraph")
    def test_dbt_strategy_propagates_exception(
        self, mock_graph_cls, mock_cache_cls, mock_run_dbt, mock_resolve
    ):
        mock_graph_cls.side_effect = RuntimeError("manifest not found")

        args = _make_args(comparison_strategy="dbt")
        with pytest.raises(Exception, match="manifest not found"):
            dbt_strategy(args)


# ---------------------------------------------------------------------------
# hybrid_strategy
# ---------------------------------------------------------------------------

class TestHybridStrategy:
    """Tests for the hybrid (dbt state:modified + git diff filter) strategy."""

    @patch("dbt_ci.commands.init.state_modified.get_structured_modified_nodes")
    @patch("dbt_ci.commands.init.state_modified.get_nodes")
    @patch("dbt_ci.commands.init.state_modified.get_new_nodes")
    @patch("dbt_ci.commands.init.state_modified.get_deleted_nodes")
    @patch("dbt_ci.commands.init.state_modified.resolve_dbt_commands")
    @patch("dbt_ci.commands.init.state_modified.run_dbt_command")
    @patch("dbt_ci.commands.init.state_modified.CacheManager")
    @patch("dbt_ci.commands.init.state_modified.GitAdapter")
    @patch("dbt_ci.commands.init.state_modified.DbtGraph")
    def test_node_not_in_git_diff_is_excluded(
        self, mock_graph_cls, mock_git_cls, mock_cache_cls, mock_run_dbt,
        mock_resolve, mock_deleted, mock_new, mock_get_nodes, mock_structured
    ):
        """A node flagged by dbt state:modified but absent from git diff should be excluded."""
        target_nodes = {
            "model.project.model1": {"original_file_path": "models/model1.sql"},
        }
        target_dict = _make_graph_dict(target_nodes)
        reference_dict = _make_graph_dict({})

        mock_target = MagicMock()
        mock_target.to_dict.return_value = target_dict
        mock_reference = MagicMock()
        mock_reference.to_dict.return_value = reference_dict
        mock_graph_cls.side_effect = lambda *a, **kw: (
            mock_reference if kw.get("is_reference") else mock_target
        )

        mock_resolve.return_value = ["ls"]
        mock_run_dbt.return_value = CompletedProcess(args=[], returncode=0, stdout="model1", stderr="")
        mock_cache_cls.return_value = MagicMock()
        mock_deleted.return_value = []
        mock_new.return_value = []

        # git diff shows NO changed files → model1 should be filtered out
        mock_git_cls.return_value.get_changed_files.return_value = {
            "modified": set(),
            "added": set(),
            "deleted": set(),
        }

        mock_get_nodes.return_value = {
            "model.project.model1": {"original_file_path": "models/model1.sql"}
        }
        mock_structured.return_value = {}

        args = _make_args(comparison_strategy="hybrid")
        result = hybrid_strategy(args)

        assert result["modified_nodes"] == {}

    @patch("dbt_ci.commands.init.state_modified.get_structured_modified_nodes")
    @patch("dbt_ci.commands.init.state_modified.get_nodes")
    @patch("dbt_ci.commands.init.state_modified.get_new_nodes")
    @patch("dbt_ci.commands.init.state_modified.get_deleted_nodes")
    @patch("dbt_ci.commands.init.state_modified.resolve_dbt_commands")
    @patch("dbt_ci.commands.init.state_modified.run_dbt_command")
    @patch("dbt_ci.commands.init.state_modified.CacheManager")
    @patch("dbt_ci.commands.init.state_modified.GitAdapter")
    @patch("dbt_ci.commands.init.state_modified.DbtGraph")
    def test_node_in_both_dbt_and_git_is_included(
        self, mock_graph_cls, mock_git_cls, mock_cache_cls, mock_run_dbt,
        mock_resolve, mock_deleted, mock_new, mock_get_nodes, mock_structured
    ):
        """A node present in both dbt state:modified and git diff should be included."""
        target_nodes = {
            "model.project.model1": {"original_file_path": "models/model1.sql"},
        }
        target_dict = _make_graph_dict(target_nodes)
        reference_dict = _make_graph_dict({})

        mock_target = MagicMock()
        mock_target.to_dict.return_value = target_dict
        mock_reference = MagicMock()
        mock_reference.to_dict.return_value = reference_dict
        mock_graph_cls.side_effect = lambda *a, **kw: (
            mock_reference if kw.get("is_reference") else mock_target
        )

        mock_resolve.return_value = ["ls"]
        mock_run_dbt.return_value = CompletedProcess(args=[], returncode=0, stdout="model1", stderr="")
        mock_cache_cls.return_value = MagicMock()
        mock_deleted.return_value = []
        mock_new.return_value = []

        mock_git_cls.return_value.get_changed_files.return_value = {
            "modified": {"models/model1.sql"},
            "added": set(),
            "deleted": set(),
        }

        mock_get_nodes.return_value = {
            "model.project.model1": {"original_file_path": "models/model1.sql"}
        }
        mock_structured.return_value = {"model": {"model.project.model1": {}}}

        args = _make_args(comparison_strategy="hybrid")
        result = hybrid_strategy(args)

        assert result["modified_nodes"] == {"model": {"model.project.model1": {}}}

    @patch("dbt_ci.commands.init.state_modified.GitAdapter")
    @patch("dbt_ci.commands.init.state_modified.DbtGraph")
    @patch("dbt_ci.commands.init.state_modified.CacheManager")
    @patch("dbt_ci.commands.init.state_modified.run_dbt_command")
    @patch("dbt_ci.commands.init.state_modified.resolve_dbt_commands")
    def test_exception_exits(
        self, mock_resolve, mock_run_dbt, mock_cache_cls, mock_graph_cls, mock_git_cls
    ):
        mock_graph_cls.side_effect = RuntimeError("graph error")

        args = _make_args(comparison_strategy="hybrid")
        with pytest.raises(SystemExit) as exc_info:
            hybrid_strategy(args)
        assert exc_info.value.code == 1
