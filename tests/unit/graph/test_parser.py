"""Unit tests for dependency graph construction."""
from dbt_ci.graph.parser import compute_transitive_closure, generate_dependency_graph


def _model(name: str, parents: list[str]) -> dict:
    """Build a minimal manifest node entry for a model."""
    return {
        "name": name,
        "resource_type": "model",
        "database": "db",
        "schema": "sc",
        "original_file_path": f"models/{name}.sql",
        "config": {"materialized": "table"},
        "columns": {},
        "depends_on": {"macros": [], "nodes": parents},
    }


def _manifest(edges: dict[str, list[str]]) -> dict:
    """Build a manifest from a {node: [parents]} mapping."""
    nodes = {
        f"model.pkg.{name}": _model(name, [f"model.pkg.{p}" for p in parents])
        for name, parents in edges.items()
    }
    parent_map = {node_id: node["depends_on"]["nodes"] for node_id, node in nodes.items()}
    child_map = {
        node_id: [child for child, parents in parent_map.items() if node_id in parents]
        for node_id in nodes
    }
    return {
        "metadata": {},
        "nodes": nodes,
        "macros": {},
        "sources": {},
        "parent_map": parent_map,
        "child_map": child_map,
    }


class TestTransitiveClosure:
    """Test the memoised closure used for indirect dependencies."""

    def test_linear_chain_collects_every_ancestor(self):
        """a -> b -> c means c's indirect upstream contains both b and a."""
        graph = generate_dependency_graph(_manifest({"a": [], "b": ["a"], "c": ["b"]}))

        upstream = graph["model"]["model.pkg.c"]["indirect_upstream_dependencies"]["node_dependencies"]

        assert upstream == {"model.pkg.b", "model.pkg.a"}

    def test_closure_includes_direct_dependencies(self):
        """The 'indirect' set is the full closure, direct dependencies included."""
        graph = generate_dependency_graph(_manifest({"a": [], "b": ["a"]}))

        assert graph["model"]["model.pkg.b"]["indirect_upstream_dependencies"]["node_dependencies"] == {
            "model.pkg.a"
        }

    def test_downstream_closure(self):
        """a's indirect downstream contains everything that reads from it, transitively."""
        graph = generate_dependency_graph(_manifest({"a": [], "b": ["a"], "c": ["b"]}))

        downstream = graph["model"]["model.pkg.a"]["indirect_downstream_dependencies"]["node_dependencies"]

        assert downstream == {"model.pkg.b", "model.pkg.c"}

    def test_diamond_is_not_double_counted(self):
        """A node reachable by two paths appears once."""
        graph = generate_dependency_graph(
            _manifest({"a": [], "b": ["a"], "c": ["a"], "d": ["b", "c"]})
        )

        upstream = graph["model"]["model.pkg.d"]["indirect_upstream_dependencies"]["node_dependencies"]

        assert upstream == {"model.pkg.b", "model.pkg.c", "model.pkg.a"}

    def test_dependencies_by_type_is_populated(self):
        """Closure members are also grouped by resource type, keyed by node name."""
        graph = generate_dependency_graph(_manifest({"a": [], "b": ["a"], "c": ["b"]}))

        by_type = graph["model"]["model.pkg.c"]["indirect_upstream_dependencies"]["dependencies_by_type"]

        assert by_type["model"] == {"model.pkg.a", "model.pkg.b"}

    def test_deep_chain_does_not_exhaust_the_recursion_limit(self):
        """A chain deeper than Python's recursion limit must still resolve."""
        depth = 2000
        edges = {"m0": []}
        for i in range(1, depth):
            edges[f"m{i}"] = [f"m{i - 1}"]

        graph = generate_dependency_graph(_manifest(edges))

        deepest = graph["model"][f"model.pkg.m{depth - 1}"]
        assert len(deepest["indirect_upstream_dependencies"]["node_dependencies"]) == depth - 1

    def test_cycle_terminates(self):
        """A cyclic manifest must not loop forever, even though dbt DAGs are acyclic."""
        graph = generate_dependency_graph(_manifest({"a": ["b"], "b": ["a"]}))

        upstream = graph["model"]["model.pkg.a"]["indirect_upstream_dependencies"]["node_dependencies"]

        assert "model.pkg.b" in upstream

    def test_memo_is_reused_across_calls(self):
        """A populated memo short-circuits repeated closure computation."""
        adjacency = {"a": {"b"}, "b": {"c"}, "c": set()}
        memo: dict[str, set[str]] = {}

        first = compute_transitive_closure("a", adjacency, memo)

        assert first == {"b", "c"}
        assert memo["b"] == {"c"}
        # Serving from the memo must not depend on the adjacency map any more.
        assert compute_transitive_closure("a", {}, memo) == {"b", "c"}

    def test_unknown_dependency_ids_are_retained(self):
        """Dependencies on nodes absent from the graph are still recorded."""
        manifest = _manifest({"a": []})
        manifest["parent_map"]["model.pkg.a"] = ["operation.pkg.hook"]
        manifest["nodes"]["model.pkg.a"]["depends_on"]["nodes"] = ["operation.pkg.hook"]

        graph = generate_dependency_graph(manifest)

        assert "operation.pkg.hook" in (
            graph["model"]["model.pkg.a"]["indirect_upstream_dependencies"]["node_dependencies"]
        )
