"""Unit tests for state comparison strategies."""
from argparse import Namespace
from unittest.mock import patch

import pytest

from dbt_ci.commands.init.state_modified import StateModified


def _args(**overrides) -> Namespace:
    """Build an args namespace with the keys the strategies read."""
    defaults = {
        "comparison_strategy": "hybrid",
        "dbt_project_dir": "dbt",
        "reference_target": "production",
        "reference_vars": None,
        "runner": "dbt",
    }
    defaults.update(overrides)
    return Namespace(**defaults)


class TestGraphReuse:
    """Test that manifests are parsed once per command rather than once per lookup."""

    def test_target_graph_is_built_once(self):
        """Repeated access reuses the parsed graph instead of re-reading the manifest."""
        state = StateModified(_args())

        with patch("dbt_ci.commands.init.state_modified.DbtGraph") as mock_graph:
            mock_graph.return_value.to_dict.return_value = {"model": {}}
            first = state.target_graph
            second = state.target_graph

        assert first is second
        mock_graph.assert_called_once()

    def test_reference_graph_is_built_once(self):
        """The reference graph is cached independently of the target graph."""
        state = StateModified(_args())

        with patch("dbt_ci.commands.init.state_modified.DbtGraph") as mock_graph:
            mock_graph.return_value.to_dict.return_value = {"model": {}}
            state.reference_graph
            state.reference_graph

        mock_graph.assert_called_once_with(state.args, is_reference=True)

    def test_hybrid_strategy_builds_each_graph_once(self):
        """Hybrid previously rebuilt both graphs twice: once directly, once via dbt state."""
        state = StateModified(_args())
        empty_graph = {"metadata": {}, "model": {}}

        with patch("dbt_ci.commands.init.state_modified.DbtGraph") as mock_graph, \
             patch("dbt_ci.commands.init.state_modified.GitAdapter") as mock_git, \
             patch.object(StateModified, "common_state_change") as mock_common:
            mock_graph.return_value.to_dict.return_value = empty_graph
            mock_git.return_value.get_changed_files.return_value = {}
            mock_common.return_value = {
                "modified_node_ids": set(),
                "deleted_node_ids": set(),
                "new_node_ids": set(),
            }

            state.hybrid_strategy()

        # One target graph + one reference graph, and no more.
        assert mock_graph.call_count == 2


class TestGetStateModified:
    """Test strategy dispatch."""

    @pytest.mark.parametrize(
        "strategy,method",
        [("git", "git_strategy"), ("hybrid", "hybrid_strategy"), ("dbt", "dbt_strategy")],
    )
    def test_dispatches_to_the_configured_strategy(self, strategy, method):
        """Each configured strategy routes to its implementation."""
        state = StateModified(_args(comparison_strategy=strategy))

        with patch.object(StateModified, method) as mock_method:
            state.get_state_modified()

        mock_method.assert_called_once()

    def test_invalid_strategy_exits(self):
        """An unrecognised strategy is a configuration error."""
        state = StateModified(_args(comparison_strategy="magic"))

        with pytest.raises(SystemExit):
            state.get_state_modified()
