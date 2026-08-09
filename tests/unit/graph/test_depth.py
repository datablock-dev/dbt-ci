"""Unit tests for depth-limited dependency selection."""
from dbt_ci.graph.graph_utils import (
    collect_dependencies_to_depth,
    get_downstream_dependencies,
    get_upstream_dependencies,
)


def _node(unique_id: str, downstream: list[str], upstream: list[str]) -> dict:
    """Build a graph node carrying only the edges the traversal reads."""
    return {
        "id": unique_id,
        "name": unique_id.split(".")[-1],
        "resource_type": unique_id.split(".")[0],
        "downstream_dependencies": {"node_dependencies": set(downstream), "dependencies_by_type": {}},
        "upstream_dependencies": {"node_dependencies": set(upstream), "dependencies_by_type": {}},
    }


def _chain_graph() -> dict:
    """a -> b -> c -> d, with a second branch a -> e, and a test hanging off b."""
    edges = {
        "model.p.a": (["model.p.b", "model.p.e"], []),
        "model.p.b": (["model.p.c", "test.p.b_is_valid"], ["model.p.a"]),
        "model.p.c": (["model.p.d"], ["model.p.b"]),
        "model.p.d": ([], ["model.p.c"]),
        "model.p.e": ([], ["model.p.a"]),
        "test.p.b_is_valid": ([], ["model.p.b"]),
    }
    graph: dict = {"metadata": {}, "model": {}, "test": {}}
    for unique_id, (down, up) in edges.items():
        graph[unique_id.split(".")[0]][unique_id] = _node(unique_id, down, up)
    return graph


class TestCollectDependenciesToDepth:
    """Test the bounded breadth-first traversal."""

    def test_depth_zero_selects_nothing(self):
        """Depth 0 means "only what changed" - no dependencies at all."""
        assert collect_dependencies_to_depth(_chain_graph(), ["model.p.a"], "downstream", 0) == set()

    def test_depth_one_selects_direct_children_only(self):
        """One hop reaches both branches but goes no further."""
        result = collect_dependencies_to_depth(_chain_graph(), ["model.p.a"], "downstream", 1)
        assert result == {"model.p.b", "model.p.e"}

    def test_depth_accumulates_each_level(self):
        """Each additional level adds the next ring, keeping the earlier ones."""
        graph = _chain_graph()
        two = collect_dependencies_to_depth(graph, ["model.p.a"], "downstream", 2)
        assert two == {"model.p.b", "model.p.e", "model.p.c", "test.p.b_is_valid"}

    def test_depth_beyond_the_graph_is_the_full_closure(self):
        """Asking for more levels than exist simply stops early."""
        graph = _chain_graph()
        deep = collect_dependencies_to_depth(graph, ["model.p.a"], "downstream", 99)
        assert deep == {
            "model.p.b", "model.p.c", "model.p.d", "model.p.e", "test.p.b_is_valid",
        }

    def test_upstream_direction(self):
        """The same traversal walks ancestors when asked."""
        result = collect_dependencies_to_depth(_chain_graph(), ["model.p.d"], "upstream", 2)
        assert result == {"model.p.c", "model.p.b"}

    def test_unknown_start_node_is_skipped(self):
        """A node id absent from the graph contributes nothing and does not raise."""
        assert collect_dependencies_to_depth(_chain_graph(), ["model.p.ghost"], "downstream", 3) == set()

    def test_cycle_terminates(self):
        """A cyclic graph must not loop forever."""
        graph = {
            "metadata": {},
            "model": {
                "model.p.a": _node("model.p.a", ["model.p.b"], ["model.p.b"]),
                "model.p.b": _node("model.p.b", ["model.p.a"], ["model.p.a"]),
            },
        }
        assert collect_dependencies_to_depth(graph, ["model.p.a"], "downstream", 99) == {
            "model.p.a", "model.p.b",
        }


class TestDepthThroughPublicHelpers:
    """Test that levels= is honoured by the selection helpers the commands call."""

    def test_downstream_levels_limits_selection(self):
        """levels caps how far a change propagates."""
        graph = _chain_graph()
        assert get_downstream_dependencies(graph, ["model.p.a"], levels=1) == {
            "model.p.b", "model.p.e",
        }

    def test_downstream_levels_zero_returns_none(self):
        """Depth 0 yields no dependencies, reported as None like an empty result."""
        assert get_downstream_dependencies(_chain_graph(), ["model.p.a"], levels=0) is None

    def test_downstream_levels_respects_node_type(self):
        """Type filtering still applies within the depth limit."""
        graph = _chain_graph()
        result = get_downstream_dependencies(graph, ["model.p.a"], node_type="test", levels=2)
        assert result == {"test.p.b_is_valid"}

    def test_omitting_levels_uses_the_full_closure(self):
        """Without levels the precomputed closure is used, preserving prior behaviour."""
        graph = _chain_graph()
        # The closure lives in indirect_*; provide it for the node under test.
        graph["model"]["model.p.a"]["indirect_downstream_dependencies"] = {
            "node_dependencies": {"model.p.b", "model.p.c", "model.p.d", "model.p.e"},
            "dependencies_by_type": {"model": {"model.p.b", "model.p.c", "model.p.d", "model.p.e"}},
        }
        assert get_downstream_dependencies(graph, ["model.p.a"]) == {
            "model.p.b", "model.p.c", "model.p.d", "model.p.e",
        }

    def test_upstream_levels_filters_by_type(self):
        """Upstream depth honours the node_type filter too."""
        graph = _chain_graph()
        result = get_upstream_dependencies(graph, ["model.p.d"], node_type=["model"], levels=1)
        assert result == {"model.p.c"}
