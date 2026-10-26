"""Getters for dependency graph nodes"""

import logging
from typing import Literal
from dbt_ci.schema import (
    DependencyGraph,
    DependencyGraphNode,
    DependencyGraphNodeType,
    NodesById,
    StructuredNodes,
)

logger = logging.getLogger(__name__)


def get_deleted_nodes(
    reference_dependency_graph: DependencyGraph, target_dependency_graph: DependencyGraph
) -> list[str] | None:
    """Get nodes that exist in the reference graph but no longer exist in the target graph."""
    return get_diff_nodes(
        source_graph=reference_dependency_graph, reference_graph=target_dependency_graph
    )


def get_new_nodes(
    reference_dependency_graph: DependencyGraph, target_dependency_graph: DependencyGraph
) -> list[str] | None:
    """Get nodes that exist in the target graph but did not exist in the reference graph."""
    return get_diff_nodes(
        source_graph=target_dependency_graph, reference_graph=reference_dependency_graph
    )


def get_diff_nodes(
    source_graph: DependencyGraph,
    reference_graph: DependencyGraph,
) -> list[str]:
    """
    Return node names that exist in source_graph but not in reference_graph.
    """
    diff_nodes: list[str] = []

    for node_type, node_values in source_graph.items():
        for node_name in node_values.keys():
            exists = reference_graph.get(node_type, {}).get(node_name)
            if not exists:
                diff_nodes.append(node_name)

    return diff_nodes


def get_structured_modified_nodes(nodes: NodesById | None) -> StructuredNodes | None:
    """Group nodes keyed by unique_id into buckets keyed by resource type."""
    if nodes is None or len(nodes) == 0:
        return None

    structured_nodes: StructuredNodes = {}
    for node_name, node_value in nodes.items():
        node_type = node_value.get("resource_type", None)
        if node_type is None:
            continue
        elif node_type not in structured_nodes:
            structured_nodes[node_type] = {}

        structured_nodes[node_type][node_name] = node_value

    return structured_nodes


def get_node(dependency_graph: DependencyGraph, node_id: str) -> DependencyGraphNode | None:
    """
    Get a single node by its dbt unique_id.

    The unique_id's first segment is the resource type ("model.pkg.name" -> "model"),
    which addresses the right bucket directly. Nodes used to be keyed by bare name, so a
    lookup had to scan every bucket and returned whichever type came first - meaning a
    model always shadowed a singular test of the same name.
    """
    if not node_id or not isinstance(node_id, str):
        return None

    node_type = node_id.split(".")[0]
    bucket = dependency_graph.get(node_type)
    if not isinstance(bucket, dict):
        return None

    return bucket.get(node_id)


def get_nodes(
    dependency_graph: DependencyGraph,
    node_ids: list[str] | None,
    exclude_node_ids: list[str] | None = None,
) -> NodesById | None:
    """Get the nodes with the given unique_ids, leaving out unknown and excluded ones."""
    if node_ids is None or len(node_ids) == 0:
        return None

    nodes: NodesById = {}
    for node_id in node_ids:
        node = get_node(dependency_graph, node_id)
        if node is None:
            continue
        if exclude_node_ids and node_id in exclude_node_ids:
            continue
        nodes[node_id] = node
    return nodes or None


def get_node_ids_from_structured_nodes(
    structured_nodes: StructuredNodes | None,
) -> list[str] | None:
    """Extract node IDs from structured nodes dictionary."""
    if structured_nodes is None or len(structured_nodes.keys()) == 0:
        return None

    node_ids: set[str] = set()
    for nodes in structured_nodes.values():
        node_ids.update(nodes.keys())

    return list(node_ids) if len(node_ids) > 0 else None


def collect_dependencies_to_depth(
    dependency_graph: DependencyGraph,
    node_ids: list[str],
    direction: Literal["upstream", "downstream"] = "downstream",
    depth: int | None = 1,
) -> set[str]:
    """
    Walk `depth` hops out from the given nodes, following direct edges only.

    A depth of None walks the whole closure, and a depth of 0 selects nothing beyond the
    starting nodes, which is how a caller asks for "just what changed". Closures are
    walked on demand rather than precomputed for every node, which is quadratic in the
    size of the project. Every id reached is kept, including ids of resource types the
    graph does not track, but only tracked nodes are walked through.
    """
    reached: set[str] = set()
    frontier: list[str] = list(node_ids)
    hops = 0

    while frontier and (depth is None or hops < depth):
        next_frontier: list[str] = []
        for node_id in frontier:
            node = get_node(dependency_graph, node_id)
            if node is None:
                continue
            edges = (
                node["downstream_dependencies"]
                if direction == "downstream"
                else node["upstream_dependencies"]
            )
            for dep_id in edges["node_dependencies"]:
                if dep_id in reached:
                    continue
                reached.add(dep_id)
                next_frontier.append(dep_id)
        frontier = next_frontier
        hops += 1

    return reached


def get_downstream_dependencies(
    dependency_graph: DependencyGraph,
    node_ids: list[str] | None,
    node_type: DependencyGraphNodeType | None = None,
    levels: int | None = None,
) -> set[str] | None:
    """
    Get downstream dependencies for a list of node IDs, optionally of one type only.

    Defaults to the full downstream closure when levels is not specified. Only resource
    types the graph tracks are returned.
    """
    if node_ids is None or len(node_ids) == 0:
        return None

    for node_id in node_ids:
        if get_node(dependency_graph, node_id) is None:
            logger.warning(
                f"Node ID '{node_id}' not found in dependency graph when attempting to get "
                "downstream dependencies."
            )

    tracked_types = {node_type} if node_type else set(dependency_graph)
    downstream_dependencies = {
        dep_id
        for dep_id in collect_dependencies_to_depth(
            dependency_graph, node_ids, "downstream", levels
        )
        if dep_id.split(".")[0] in tracked_types
    }
    return downstream_dependencies or None


def get_upstream_dependencies(
    dependency_graph: DependencyGraph,
    node_ids: list[str] | None,
    node_type: list[DependencyGraphNodeType] | None = None,
    filters: list[DependencyGraphNodeType] | None = None,
    levels: int | None = None,
) -> set[str] | None:
    """Get upstream dependencies for a list of node IDs, optionally up to a number of levels."""
    if node_ids is None or len(node_ids) == 0:
        return None

    if levels is not None:
        upstream_dependencies = collect_dependencies_to_depth(
            dependency_graph, node_ids, "upstream", levels
        )
        allowed = set(node_type or []) | set(filters or [])
        if allowed:
            upstream_dependencies = {
                dep_id
                for dep_id in upstream_dependencies
                if (node := get_node(dependency_graph, dep_id))
                and node.get("resource_type") in allowed
            }
        return upstream_dependencies or None

    upstream_dependencies = set()
    for node_id in node_ids:
        node = get_node(dependency_graph, node_id)
        if node is None:
            continue

        for dep_type, dep_names in node["upstream_dependencies"]["dependencies_by_type"].items():
            if node_type and dep_type not in node_type:
                continue
            if filters and dep_type not in filters:
                continue
            if dep_names and len(dep_names) > 0:
                upstream_dependencies.update(dep_names)

    if len(upstream_dependencies) == 0:
        return None
    return upstream_dependencies


def filter_node_ids_by_type(
    dependency_graph: DependencyGraph, node_ids: list[str], node_type: list[DependencyGraphNodeType]
) -> list[str]:
    """Filter a list of node IDs by type."""
    filtered_node_ids = []
    for node_id in node_ids:
        node = get_node(dependency_graph, node_id)
        if node and node.get("resource_type") in node_type:
            filtered_node_ids.append(node_id)
    return filtered_node_ids


def get_relation_name(node: DependencyGraphNode | dict) -> str | None:
    """
    Return the table/view name dbt builds for a node.

    The alias dbt resolved is preferred, since a custom generate_alias_name macro can
    make it differ from both the node name and config.alias.
    """
    return node.get("alias") or (node.get("config") or {}).get("alias") or node.get("name")


def get_nodes_from_path(
    dependency_graph: DependencyGraph,
    path: str,
    include_patch_path: bool = False,
) -> list[DependencyGraphNode]:
    """
    Get every node defined by a given file.

    One file commonly defines several nodes - a schema.yml declares many tests, and a
    model's .sql file and its tests can share a path - so change detection has to
    consider all of them rather than the first match. With include_patch_path, nodes
    whose properties (config, contract, columns) live in that YAML file match too.
    """
    matches: list[DependencyGraphNode] = []
    for node_values in dependency_graph.values():
        for node_info in node_values.values():
            if node_info.get("original_file_path", None) == path or (
                include_patch_path and node_info.get("patch_path", None) == path
            ):
                matches.append(node_info)
    return matches


def get_nodes_using_macros(dependency_graph: DependencyGraph, macro_ids: set[str]) -> set[str]:
    """
    Return the non-macro nodes that call any of the given macros.

    The upstream edges are walked in reverse from the macros, so a node is a user when
    it reaches a changed macro directly, through other macros, or through a model it
    reads that calls one.
    """
    if not macro_ids:
        return set()

    callers: dict[str, set[str]] = {}
    for node_values in dependency_graph.values():
        for node_id, node_info in node_values.items():
            for dep_id in node_info["upstream_dependencies"]["node_dependencies"]:
                callers.setdefault(dep_id, set()).add(node_id)

    reached: set[str] = set()
    frontier = list(macro_ids)
    while frontier:
        next_frontier: list[str] = []
        for node_id in frontier:
            for caller_id in callers.get(node_id, ()):
                if caller_id not in reached:
                    reached.add(caller_id)
                    next_frontier.append(caller_id)
        frontier = next_frontier

    return {node_id for node_id in reached if not node_id.startswith("macro.")}


def get_display_name(dependency_graph: DependencyGraph | None, node_id: str) -> str:
    """
    Return a human-readable name for a unique_id.

    Splitting the id on '.' is not enough: a generic test's unique_id ends in a hash
    (test.pkg.not_null_customers_id.422908bfae), so the node's own name is preferred
    whenever the graph is available.
    """
    if dependency_graph is not None:
        node = get_node(dependency_graph, node_id)
        if node and node.get("name"):
            return node["name"]
    return node_id.split(".")[-1]


def get_selectors(dependency_graph: DependencyGraph, node_ids: list[str]) -> list[str]:
    """
    Convert dbt unique_ids into selector strings for `dbt --select`.

    dbt has no `unique_id:` selector method, so the node's fqn path is used instead
    ("demo.staging.customers"). That is unambiguous across packages, whereas the bare
    name dbt-ci used to pass matches every node sharing it - selecting a vendored
    package's model alongside your own.
    """
    selectors: list[str] = []
    for node_id in node_ids:
        node = get_node(dependency_graph, node_id)
        if node is None:
            logger.warning(
                f"Node ID '{node_id}' not found in dependency graph; skipping selection."
            )
            continue

        fqn = node.get("fqn")
        if fqn:
            selectors.append(".".join(fqn))
        else:
            # Sources and any node without an fqn fall back to their name.
            selectors.append(node["name"])

    return selectors
