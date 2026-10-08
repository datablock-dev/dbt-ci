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


class TestCommonStateChangeCommand:
    """Test the dbt ls command built for state:modified."""

    @pytest.mark.parametrize(
        "overrides,expected_target,expected_vars",
        [
            ({"target": "dev", "vars": "{a: 1}"}, "production", "{b: 2}"),
            ({"target": "dev", "vars": "{a: 1}", "reference_target": None}, "dev", "{b: 2}"),
            ({"target": "dev", "vars": "{a: 1}", "reference_vars": None}, "production", "{a: 1}"),
        ],
    )
    def test_target_and_vars_are_passed_once(self, overrides, expected_target, expected_vars):
        """The reference target and vars replace the current ones instead of repeating the flag."""
        args = _args(**{"reference_vars": "{b: 2}", **overrides})
        state = StateModified(args)

        with patch("dbt_ci.commands.init.state_modified.CacheManager"), \
             patch("dbt_ci.commands.init.state_modified.run_dbt_command") as mock_run, \
             patch.object(StateModified, "target_graph", {"model": {}}), \
             patch.object(StateModified, "reference_graph", {"model": {}}):
            mock_run.return_value.stdout = ""
            state.common_state_change()

        commands = mock_run.call_args.kwargs["command_args"]
        assert commands.count("--target") == 1
        assert commands[commands.index("--target") + 1] == expected_target
        assert commands.count("--vars") == 1
        assert commands[commands.index("--vars") + 1] == expected_vars


# ---------------------------------------------------------------------------
# Classification of git and hybrid change sets against small fake manifests
# ---------------------------------------------------------------------------

from dbt_ci.graph.parser import generate_dependency_graph


def _node(name: str, path: str, macros=(), parents=(), patch_path: str | None = None) -> dict:
    """Build a manifest node entry for a model."""
    return {
        "name": name,
        "resource_type": "model",
        "database": "db",
        "schema": "sc",
        "original_file_path": path,
        "patch_path": patch_path,
        "config": {"materialized": "table"},
        "columns": {},
        "depends_on": {"macros": list(macros), "nodes": list(parents)},
    }


def _graph(nodes: dict[str, dict], macros: dict[str, dict] | None = None) -> dict:
    """Parse a manifest built from the given model and macro entries."""
    parent_map = {node_id: node["depends_on"]["nodes"] for node_id, node in nodes.items()}
    child_map = {
        node_id: [child for child, parents in parent_map.items() if node_id in parents]
        for node_id in nodes
    }
    return generate_dependency_graph({
        "metadata": {},
        "nodes": nodes,
        "macros": macros or {},
        "sources": {},
        "parent_map": parent_map,
        "child_map": child_map,
    })


MACROS = {
    "macro.pkg.cents": {"name": "cents", "original_file_path": "macros/cents.sql", "depends_on": {"macros": []}},
    "macro.pkg.fmt": {"name": "fmt", "original_file_path": "macros/fmt.sql", "depends_on": {"macros": ["macro.pkg.cents"]}},
}

BASE_NODES = {
    "model.pkg.stg": _node("stg", "models/staging/stg.sql", macros=["macro.pkg.cents"], patch_path="pkg://models/schema.yml"),
    "model.pkg.other": _node("other", "models/other.sql", macros=["macro.pkg.fmt"]),
    "model.pkg.plain": _node("plain", "models/plain.sql"),
}


def _ids(summary: dict, key: str) -> set[str]:
    """Collect the node ids under one key of a state change summary."""
    return {node_id for nodes in (summary.get(key) or {}).values() for node_id in nodes}


def _classify(strategy: str, changed_files: dict, target_nodes=None, reference_nodes=None, dbt_ids=None) -> dict:
    """Run a strategy with fixed graphs, git changes and (for hybrid) dbt state:modified ids."""
    state = StateModified(_args(comparison_strategy=strategy))
    state._target_graph = _graph(target_nodes or BASE_NODES, MACROS)
    state._reference_graph = _graph(reference_nodes or BASE_NODES, MACROS)
    dbt_ids = dbt_ids or {}

    with patch("dbt_ci.commands.init.state_modified.GitAdapter") as mock_git, \
         patch.object(StateModified, "common_state_change") as mock_common:
        mock_git.return_value.get_changed_files.return_value = changed_files
        mock_common.return_value = {
            "modified_node_ids": set(dbt_ids.get("modified", ())),
            "deleted_node_ids": set(dbt_ids.get("deleted", ())),
            "new_node_ids": set(dbt_ids.get("new", ())),
        }
        return state.get_state_modified()


MOVED_TARGET = {**BASE_NODES, "model.pkg.stg": {**BASE_NODES["model.pkg.stg"], "original_file_path": "models/marts/stg.sql"}}
MOVE = {"deleted": ["models/staging/stg.sql"], "added": ["models/marts/stg.sql"]}


@pytest.mark.parametrize("strategy", ["git", "hybrid"])
class TestChangeClassification:
    """Test that git's file-level changes are mapped onto the right nodes."""

    def test_moved_model_is_modified_not_deleted(self, strategy):
        """A moved file keeps its unique_id, so it must not be reported as deleted (and dropped)."""
        summary = _classify(strategy, MOVE, target_nodes=MOVED_TARGET, dbt_ids={"modified": ["model.pkg.stg"]})
        assert _ids(summary, "modified_nodes") == {"model.pkg.stg"}
        assert _ids(summary, "deleted_nodes") == set()
        assert _ids(summary, "new_nodes") == set()

    def test_removed_model_is_still_deleted(self, strategy):
        """A model that is gone from the target is still reported as deleted."""
        target = {k: v for k, v in BASE_NODES.items() if k != "model.pkg.plain"}
        summary = _classify(strategy, {"deleted": ["models/plain.sql"]}, target_nodes=target,
                            dbt_ids={"deleted": ["model.pkg.plain"]})
        assert _ids(summary, "deleted_nodes") == {"model.pkg.plain"}

    def test_macro_change_selects_its_users(self, strategy):
        """Models calling a changed macro, directly or via another macro, are modified."""
        summary = _classify(
            strategy,
            {"modified": ["macros/cents.sql", "models/plain.sql"]},
            dbt_ids={"modified": ["model.pkg.stg", "model.pkg.other", "model.pkg.plain"]},
        )
        assert {"model.pkg.stg", "model.pkg.other", "model.pkg.plain"} <= _ids(summary, "modified_nodes")

    def test_yaml_only_change_selects_the_patched_model(self, strategy):
        """A config change made only in schema.yml marks the model it patches as modified."""
        summary = _classify(
            strategy,
            {"modified": ["models/schema.yml", "models/plain.sql"]},
            dbt_ids={"modified": ["model.pkg.stg", "model.pkg.plain"]},
        )
        assert {"model.pkg.stg", "model.pkg.plain"} <= _ids(summary, "modified_nodes")

    def test_unrelated_models_are_not_selected(self, strategy):
        """Only the nodes behind the changed files are selected."""
        summary = _classify(strategy, {"modified": ["models/plain.sql"]}, dbt_ids={"modified": ["model.pkg.plain"]})
        assert _ids(summary, "modified_nodes") == {"model.pkg.plain"}
