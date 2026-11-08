"""Explain why `run` selected each node: its own change, or its link to a changed node."""

from typing import Literal

from dbt_ci.graph.graph_utils import get_display_name, get_node
from dbt_ci.schema import DependencyGraph

# Changed nodes named before the rest are summarised as "and N more"
MAX_NAMES = 3

TEST_TYPES = ("test", "unit_test")


def explain_selection(
    graph: DependencyGraph,
    node_id: str,
    changed_ids: set[str],
    reasons: dict[str, list[str]] | None = None,
) -> str:
    """
    Return why a node is in the run, in a few words.

    A changed node gives the reasons init recorded. Anything else is in the run because
    of a changed node: a test checks it, a model or snapshot reads from it (directly or
    further up), or a seed is read by it.
    """
    if reasons and reasons.get(node_id):
        return "; ".join(reasons[node_id])

    node = get_node(graph, node_id)
    if node is None:
        return ""
    if node.get("resource_type") in TEST_TYPES:
        parents = _neighbours(graph, node_id, "upstream")
        return f"tests {_names(graph, parents)}" if parents else ""

    upstream = _nearest_changed(graph, node_id, changed_ids, "upstream")
    if upstream:
        return f"downstream of {_names(graph, upstream)}"
    downstream = _nearest_changed(graph, node_id, changed_ids, "downstream")
    if downstream:
        return f"used by {_names(graph, downstream)}"
    return ""


def _neighbours(
    graph: DependencyGraph, node_id: str, direction: Literal["upstream", "downstream"]
) -> list[str]:
    """Return a node's direct parents or children, leaving out macros."""
    node = get_node(graph, node_id)
    if node is None:
        return []
    if direction == "upstream":
        edges = node.get("upstream_dependencies")
    else:
        edges = node.get("downstream_dependencies")
    deps = (edges or {}).get("node_dependencies") or set()
    return sorted(dep for dep in deps if not dep.startswith("macro."))


def _nearest_changed(
    graph: DependencyGraph,
    node_id: str,
    changed_ids: set[str],
    direction: Literal["upstream", "downstream"],
) -> list[str]:
    """
    Return the changed nodes reached first when walking from a node in one direction.

    The walk stops at each changed node it reaches, so for a chain a -> b -> c where a
    and b changed, c is explained by b alone.
    """
    found: set[str] = set()
    seen = {node_id}
    frontier = [node_id]
    while frontier:
        next_frontier: list[str] = []
        for current in frontier:
            for neighbour in _neighbours(graph, current, direction):
                if neighbour in seen:
                    continue
                seen.add(neighbour)
                if neighbour in changed_ids:
                    found.add(neighbour)
                else:
                    next_frontier.append(neighbour)
        frontier = next_frontier
    return sorted(found)


def _names(graph: DependencyGraph, node_ids: list[str]) -> str:
    """List a few node names in backticks, summarising the rest."""
    names = [f"`{get_display_name(graph, node_id)}`" for node_id in node_ids[:MAX_NAMES]]
    more = len(node_ids) - MAX_NAMES
    return ", ".join(names) + (f" and {more} more" if more > 0 else "")
