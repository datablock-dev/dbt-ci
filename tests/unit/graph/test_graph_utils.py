"""Unit tests for dependency graph lookups and selector construction.

The fixtures mirror collisions confirmed against a real dbt project: dbt permits a model
and a singular test to share a name, and permits two packages to define the same model
name as long as their database representations differ.
"""
from dbt_ci.graph.graph_utils import (
    get_display_name,
    get_node,
    get_nodes_from_path,
    get_selectors,
)


def _node(unique_id: str, fqn: list[str], path: str) -> dict:
    """Build a graph node entry."""
    return {
        "id": unique_id,
        "name": unique_id.split(".")[-1],
        "fqn": fqn,
        "original_file_path": path,
        "resource_type": unique_id.split(".")[0],
    }


COLLIDING_GRAPH = {
    "metadata": {},
    "model": {
        "model.demo.customers": _node(
            "model.demo.customers", ["demo", "staging", "customers"], "models/staging/customers.sql"
        ),
        "model.mypkg.customers": _node(
            "model.mypkg.customers", ["mypkg", "customers"], "models/customers.sql"
        ),
    },
    "test": {
        "test.demo.customers": _node(
            "test.demo.customers", ["demo", "customers"], "tests/customers.sql"
        ),
    },
    "seed": {},
    "snapshot": {},
    "macro": {},
    "exposure": {},
    "source": {},
}


class TestGetNode:
    """Test node lookup by unique_id."""

    def test_resolves_each_colliding_node_to_itself(self):
        """A shared name must not make one node shadow another."""
        for unique_id in ("model.demo.customers", "model.mypkg.customers", "test.demo.customers"):
            node = get_node(COLLIDING_GRAPH, unique_id)
            assert node is not None, f"{unique_id} was not found"
            assert node["id"] == unique_id

    def test_bare_name_no_longer_resolves(self):
        """Names are not identifiers; only unique_ids address a node."""
        assert get_node(COLLIDING_GRAPH, "customers") is None

    def test_unknown_id_returns_none(self):
        """A missing node is reported rather than raising."""
        assert get_node(COLLIDING_GRAPH, "model.demo.absent") is None

    def test_non_string_id_returns_none(self):
        """Defensive: a None id must not raise."""
        assert get_node(COLLIDING_GRAPH, None) is None


class TestGetSelectors:
    """Test conversion of unique_ids into dbt --select arguments."""

    def test_uses_fqn_paths(self):
        """fqn distinguishes same-named nodes; a bare name would match all of them."""
        selectors = get_selectors(
            COLLIDING_GRAPH, ["model.demo.customers", "model.mypkg.customers"]
        )
        assert selectors == ["demo.staging.customers", "mypkg.customers"]

    def test_falls_back_to_name_without_fqn(self):
        """Nodes carrying no fqn still yield a usable selector."""
        graph = {"metadata": {}, "model": {"model.demo.x": {"id": "model.demo.x", "name": "x", "fqn": None}}}
        assert get_selectors(graph, ["model.demo.x"]) == ["x"]

    def test_skips_unknown_nodes(self):
        """An unresolvable id is dropped rather than emitting a broken selector."""
        assert get_selectors(COLLIDING_GRAPH, ["model.demo.absent"]) == []


class TestGetNodesFromPath:
    """Test resolving every node defined by a file."""

    def test_returns_all_nodes_at_a_path(self):
        """A schema.yml defines many tests, so all of them must be attributed."""
        graph = {
            "metadata": {},
            "test": {
                "test.demo.a": _node("test.demo.a", ["demo", "a"], "models/schema.yml"),
                "test.demo.b": _node("test.demo.b", ["demo", "b"], "models/schema.yml"),
            },
        }
        ids = {node["id"] for node in get_nodes_from_path(graph, "models/schema.yml")}
        assert ids == {"test.demo.a", "test.demo.b"}

    def test_returns_empty_for_unknown_path(self):
        """A non-dbt file yields no nodes."""
        assert get_nodes_from_path(COLLIDING_GRAPH, "README.md") == []


class TestGetDisplayName:
    """Test human-readable rendering of unique_ids."""

    def test_uses_the_node_name(self):
        """Generic test ids end in a hash, so the node's own name is preferred."""
        graph = {
            "metadata": {},
            "test": {
                "test.demo.not_null_customers_id.422908bfae": {
                    "id": "test.demo.not_null_customers_id.422908bfae",
                    "name": "not_null_customers_id",
                }
            },
        }
        name = get_display_name(graph, "test.demo.not_null_customers_id.422908bfae")
        assert name == "not_null_customers_id"

    def test_falls_back_to_the_last_segment(self):
        """Without a graph the id's last segment is the best available label."""
        assert get_display_name(None, "model.demo.customers") == "customers"
