"""Unit tests for dependency graph construction."""

from dbt_ci.graph.graph_utils import collect_dependencies_to_depth, get_downstream_dependencies
from dbt_ci.graph.parser import generate_dependency_graph, normalize_node_ids


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


class TestTransitiveDependencies:
    """Closures are walked on demand over the direct edges the parser records."""

    def upstream(self, edges: dict[str, list[str]], node: str) -> set[str]:
        """Return every ancestor of a node in a graph built from {node: [parents]}."""
        graph = generate_dependency_graph(_manifest(edges))
        return collect_dependencies_to_depth(graph, [f"model.pkg.{node}"], "upstream", None)

    def test_linear_chain_collects_every_ancestor(self):
        """a -> b -> c means c's ancestors are both b and a."""
        assert self.upstream({"a": [], "b": ["a"], "c": ["b"]}, "c") == {
            "model.pkg.a",
            "model.pkg.b",
        }

    def test_downstream_closure(self):
        """a's descendants include everything that reads from it, transitively."""
        graph = generate_dependency_graph(_manifest({"a": [], "b": ["a"], "c": ["b"]}))
        assert get_downstream_dependencies(graph, ["model.pkg.a"]) == {"model.pkg.b", "model.pkg.c"}

    def test_diamond_is_collected_once(self):
        """Converging paths reach a shared ancestor once."""
        edges = {"a": [], "b": ["a"], "c": ["a"], "d": ["b", "c"]}
        assert self.upstream(edges, "d") == {"model.pkg.a", "model.pkg.b", "model.pkg.c"}

    def test_deep_chain_does_not_exhaust_the_recursion_limit(self):
        """A chain deeper than Python's recursion limit must still resolve."""
        depth = 2000
        edges = {"m0": []}
        for i in range(1, depth):
            edges[f"m{i}"] = [f"m{i - 1}"]

        assert len(self.upstream(edges, f"m{depth - 1}")) == depth - 1

    def test_cycle_terminates(self):
        """A cyclic manifest must not loop forever, even though dbt DAGs are acyclic."""
        assert "model.pkg.b" in self.upstream({"a": ["b"], "b": ["a"]}, "a")

    def test_parser_stores_direct_edges_only(self):
        """No closure is precomputed, which was quadratic in the size of the project."""
        graph = generate_dependency_graph(_manifest({"a": [], "b": ["a"], "c": ["b"]}))
        node = graph["model"]["model.pkg.c"]

        assert node["upstream_dependencies"]["node_dependencies"] == {"model.pkg.b"}
        assert not any(key.startswith("indirect_") for key in node)

    def test_unknown_dependency_ids_are_retained(self):
        """Dependencies on nodes absent from the graph are still recorded."""
        manifest = _manifest({"a": []})
        manifest["parent_map"]["model.pkg.a"] = ["operation.pkg.hook"]
        manifest["nodes"]["model.pkg.a"]["depends_on"]["nodes"] = ["operation.pkg.hook"]

        graph = generate_dependency_graph(manifest)

        assert "operation.pkg.hook" in (
            graph["model"]["model.pkg.a"]["upstream_dependencies"]["node_dependencies"]
        )

    def test_null_manifest_sections_are_treated_as_empty(self):
        """A manifest that writes null instead of an empty mapping still parses."""
        manifest = _manifest({"a": []})
        manifest["parent_map"] = None
        manifest["macros"] = None
        manifest["sources"] = None

        graph = generate_dependency_graph(manifest)

        assert "model.pkg.a" in graph["model"]

    def test_non_string_dependency_entries_are_reduced_to_ids(self):
        """depends_on, parent_map and child_map entries given as pairs or objects still parse."""
        manifest = _manifest({"a": [], "b": ["a"]})
        b = manifest["nodes"]["model.pkg.b"]
        b["depends_on"]["nodes"] = [["model.pkg.a", {"line": 1, "col": 5}]]
        b["depends_on"]["nodes_with_ref_location"] = [["model.pkg.a", {"line": 1}]]
        manifest["parent_map"]["model.pkg.b"] = [{"unique_id": "model.pkg.a"}]
        manifest["child_map"]["model.pkg.a"] = [["model.pkg.b", None]]

        graph = generate_dependency_graph(manifest)

        b_node = graph["model"]["model.pkg.b"]
        assert b_node["upstream_dependencies"]["node_dependencies"] == {"model.pkg.a"}
        assert graph["model"]["model.pkg.a"]["downstream_dependencies"]["node_dependencies"] == {
            "model.pkg.b"
        }

    def test_columns_given_as_a_list_are_read_by_name(self):
        """A columns field written as a list of column objects yields the column names."""
        manifest = _manifest({"a": []})
        manifest["nodes"]["model.pkg.a"]["columns"] = [{"name": "id"}, {"name": "amount"}]

        graph = generate_dependency_graph(manifest)

        assert graph["model"]["model.pkg.a"]["columns"] == {"id", "amount"}


class TestNormalizeNodeIds:
    """Tests for normalize_node_ids."""

    def test_mixed_entry_shapes(self):
        """Strings, pairs and objects are reduced to ids; unrecognised entries are dropped."""
        entries = ["model.p.a", ["model.p.b", {}], {"unique_id": "model.p.c"}, 3, [], None]

        assert normalize_node_ids(entries) == ["model.p.a", "model.p.b", "model.p.c"]

    def test_non_list_input_is_empty(self):
        """None or a scalar yields no ids."""
        assert normalize_node_ids(None) == []
        assert normalize_node_ids("model.p.a") == []
