"""Tests for explaining why run selected each node."""

from dbt_ci.commands.run.explain import explain_selection
from dbt_ci.graph.parser import generate_dependency_graph


def _graph() -> dict:
    """Parse a manifest with seed s -> a -> b -> c, a test on b and five children of c."""

    def node(name, resource_type="model", parents=()):
        """Build a manifest node entry."""
        return {
            "name": name,
            "resource_type": resource_type,
            "fqn": ["demo", name],
            "original_file_path": f"models/{name}.sql",
            "config": {},
            "columns": {},
            "depends_on": {"macros": ["macro.demo.m"], "nodes": list(parents)},
        }

    nodes = {
        "seed.demo.s": node("s", "seed"),
        "model.demo.a": node("a", parents=["seed.demo.s"]),
        "model.demo.b": node("b", parents=["model.demo.a"]),
        "model.demo.c": node("c", parents=["model.demo.b"]),
        "test.demo.t": node("t", "test", parents=["model.demo.b"]),
        **{f"model.demo.k{i}": node(f"k{i}", parents=["model.demo.c"]) for i in range(5)},
        "model.demo.z": node("z", parents=[f"model.demo.k{i}" for i in range(5)]),
    }
    parent_map = {node_id: entry["depends_on"]["nodes"] for node_id, entry in nodes.items()}
    child_map = {
        node_id: [child for child, parents in parent_map.items() if node_id in parents]
        for node_id in nodes
    }
    return generate_dependency_graph(
        {
            "metadata": {},
            "nodes": nodes,
            "macros": {},
            "sources": {},
            "parent_map": parent_map,
            "child_map": child_map,
        }
    )


class TestExplainSelection:
    """Test the reason given for each selected node."""

    def test_changed_node_uses_inits_reasons(self):
        """A changed node shows what init recorded."""
        reasons = {"model.demo.a": ["`models/a.sql` changed", "uses changed macro `m`"]}
        assert (
            explain_selection(_graph(), "model.demo.a", {"model.demo.a"}, reasons)
            == "`models/a.sql` changed; uses changed macro `m`"
        )

    def test_downstream_names_the_changed_ancestor(self):
        """A model further down names the changed model it is built for."""
        assert explain_selection(_graph(), "model.demo.c", {"model.demo.a"}) == (
            "downstream of `a`"
        )

    def test_nearest_changed_ancestor_wins(self):
        """With a and b changed, c is explained by b, the one it reads directly."""
        changed = {"model.demo.a", "model.demo.b"}
        assert explain_selection(_graph(), "model.demo.c", changed) == "downstream of `b`"

    def test_seed_names_the_changed_model_reading_it(self):
        """A seed selected for a changed model says which one reads it."""
        assert explain_selection(_graph(), "seed.demo.s", {"model.demo.a"}) == "used by `a`"

    def test_test_names_what_it_checks(self):
        """A test says which node it tests, not the macros it calls."""
        assert explain_selection(_graph(), "test.demo.t", {"model.demo.a"}) == "tests `b`"

    def test_long_lists_are_summarised(self):
        """More than three changed ancestors are counted rather than listed."""
        changed = {f"model.demo.k{i}" for i in range(5)}
        assert explain_selection(_graph(), "model.demo.z", changed) == (
            "downstream of `k0`, `k1`, `k2` and 2 more"
        )

    def test_unknown_node(self):
        """A node missing from the graph gets no reason rather than an error."""
        assert explain_selection(_graph(), "model.demo.gone", {"model.demo.a"}) == ""
