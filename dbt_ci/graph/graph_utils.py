"""Getters for dependency graph nodes"""
import logging
from typing import cast
from dbt_ci.schema import DependencyGraph, DependencyGraphNode, DependencyGraphNodeType

logger = logging.getLogger(__name__)

def get_deleted_nodes(
    target_dependency_graph: DependencyGraph,
    reference_dependency_graph: DependencyGraph
) -> list[str] | None:
    """Get deleted nodes by comparing target and reference dependency graphs."""
    return get_diff_nodes(
        source_graph=target_dependency_graph,
        compare_graph=reference_dependency_graph
    )

def get_new_nodes(
    target_dependency_graph: DependencyGraph,
    reference_dependency_graph: DependencyGraph
) -> list[str] | None:
    """Get new nodes by comparing target and reference dependency graphs."""
    return get_diff_nodes(
        source_graph=reference_dependency_graph,
        compare_graph=target_dependency_graph
    )

def get_diff_nodes(
    source_graph: DependencyGraph,
    compare_graph: DependencyGraph,
) -> list[str]:
    """
    Return node names that exist in source_graph but not in compare_graph.
    """
    diff_nodes: list[str] = []

    for node_type, node_values in source_graph.items():
        node_values = cast(dict, node_values)
        if node_type == "metadata":
            continue

        for node_name in node_values.keys():
            exists = compare_graph.get(node_type, {}).get(node_name)
            if not exists:
                diff_nodes.append(node_name)

    return diff_nodes

def get_structured_modified_nodes(nodes: dict[str, dict[str, DependencyGraphNode]] | None) -> dict[str, dict[str, DependencyGraphNode]] | None:
    """Get modified nodes, structured by type"""
    if nodes is None or len(nodes) == 0:
        return None

    structured_nodes: dict[str, dict[str, DependencyGraphNode]] = {}
    for node_name, node_value in nodes.items():
        node_type = node_value.get("resource_type", None)
        if node_type is None:
            continue
        elif node_type not in structured_nodes:
            structured_nodes[node_type] = {}

        structured_nodes[node_type][node_name] = node_value

    return structured_nodes

def get_node(dependency_graph: DependencyGraph, node_id: str) -> dict[str, DependencyGraphNode] | None:
    """Get a single node by ID, searching across all node types."""
    try:
        match = None
        for node_type in dependency_graph.keys():
            if node_type == "metadata":
                continue
            if node_id in dependency_graph[node_type]:
                match = dependency_graph[node_type][node_id]
                break
        return match
    except TypeError:
        return None
    except Exception as e:
        print(f"Error retrieving node: {e}")
        return None

def get_nodes(
    dependency_graph: DependencyGraph, 
    node_ids: list[str] | None,
    exclude_node_ids: list[str] | None = None
) -> dict[str, dict[str, DependencyGraphNode]] | None:
    """Get multiple nodes by ID, optionally filtered by type."""
    if node_ids is None or len(node_ids) == 0:
        return None

    try:
        nodes = {}
        for node_id in node_ids:
            node = get_node(dependency_graph, node_id)
            if node is None:
                continue
            if exclude_node_ids and node_id in exclude_node_ids:
                continue
            nodes[node_id] = node
        if len(nodes) == 0:
            return None
        return nodes
    except TypeError:
        return None
    except Exception as e:
        print(f"Error retrieving nodes: {e}")
        return None

def get_node_ids_from_structured_nodes(structured_nodes: dict[str, DependencyGraph] | None) -> list[str] | None:
    """Extract node IDs from structured nodes dictionary."""
    if structured_nodes is None or len(structured_nodes.keys()) == 0:
        return None

    node_ids: set[str] = set()
    for nodes in structured_nodes.values():
        for node_name in nodes.keys():
            node_ids.add(node_name)

    return list(node_ids) if len(node_ids) > 0 else None

def get_downstream_dependencies(
    dependency_graph: DependencyGraph,
    node_ids: list[str] | None,
    node_type: DependencyGraphNodeType | None = None,
    levels: int | None = None # To be implemented in the future
) -> set[str] | None:
    """
        Get downstream dependencies for a list of node IDs, 
        optionally up to a certain number of levels. Defaults to indirect downstream dependencies 
        if levels is not specified.
    """
    key = "indirect_downstream_dependencies"
    if node_ids is None or len(node_ids) == 0:
        return None
    if levels is not None:
        key = f"downstream_dependencies_level_{levels}"

    downstream_dependencies: set[str] = set()
    for node_id in node_ids:
        node = get_node(dependency_graph, node_id)
        if node is None:
            logger.warning(f"Node ID '{node_id}' not found in dependency graph when attempting to get downstream dependencies.")
            continue

        dependency_by_type: dict[DependencyGraphNodeType, list[str]] = node[key]["dependencies_by_type"]
        for dep_type, dep_names in dependency_by_type.items():
            if node_type and dep_type != node_type:
                continue
            if dep_names is not None and len(dep_names) > 0:
                downstream_dependencies.update(dep_names)

    if len(downstream_dependencies) == 0:
        return None
    return downstream_dependencies

def get_upstream_dependencies(
    dependency_graph: DependencyGraph,
    node_ids: list[str] | None,
    node_type: list[DependencyGraphNodeType] | None = None,
    filters: list[DependencyGraphNodeType] | None = None,
    levels: int | None = None # To be implemented in the future
) -> set[str] | None:
    """Get upstream dependencies for a list of node IDs, optionally up to a certain number of levels."""
    if node_ids is None or len(node_ids) == 0:
        return None

    upstream_dependencies: set[str] = set()
    for node_id in node_ids:
        node = get_node(dependency_graph, node_id)
        if node is None:
            continue

        dependency_by_type: dict[DependencyGraphNodeType, list[str]] = node["upstream_dependencies"]["dependencies_by_type"]
        for dep_type, dep_names in dependency_by_type.items():
            if node_type and dep_type not in node_type:
                continue
            if filters and dep_type not in filters:
                continue
            if dep_names and len(dep_names) > 0:
                upstream_dependencies.update(dep_names)

    if len(upstream_dependencies) == 0:
        return None
    return upstream_dependencies

def get_downstream_dependencies_from_cache(
    cache: dict[str, DependencyGraph] | None,
    node_type: DependencyGraphNodeType | None = None,
    levels: int | None = None # To be implemented in the future
) -> list[str] | None:
    """Get downstream dependencies for modified nodes from cache."""
    key = "indirect_downstream_dependencies"
    if cache is None:
        return None
    if levels is not None:
        key = f"downstream_dependencies_level_{levels}"

    downstream_dependencies: set[str] = set()
    for node_values in cache.values():
        for item_values in node_values.values():
            dependencies_by_type = item_values.get(key).get("dependencies_by_type", None)
            if dependencies_by_type:
                for dep_type, dep_names in dependencies_by_type.items():
                    if node_type and dep_type != node_type:
                        continue

                    downstream_dependencies.update(dep_names)         
    return list(downstream_dependencies) if len(downstream_dependencies) > 0 else None

def filter_node_ids_by_type(
    dependency_graph: DependencyGraph,
    node_ids: list[str],
    node_type: list[DependencyGraphNodeType]
) -> list[str]:
    """Filter a list of node IDs by type."""
    filtered_node_ids = []
    for node_id in node_ids:
        node = get_node(dependency_graph, node_id)
        if node and node.get("resource_type") in node_type:
            filtered_node_ids.append(node_id)
    return filtered_node_ids

def filter_node_ids_by_multiple_types(
    dependency_graph: DependencyGraph,
    node_ids: list[str],
    node_types: list[DependencyGraphNodeType]
) -> list[str]:
    """Filter a list of node IDs by multiple types."""
    filtered_node_ids = []
    for node_id in node_ids:
        node = get_node(dependency_graph, node_id)
        if node and node.get("resource_type") in node_types:
            filtered_node_ids.append(node_id)
    return filtered_node_ids

def get_node_from_path(dependency_graph: DependencyGraph, path: str) -> dict[str, DependencyGraphNode] | None:
    """Get a node from the dependency graph based on its path."""
    for node_type, node_values in dependency_graph.items():
        if node_type == "metadata":
            continue
        for node_info in cast(dict, node_values).values():
            if node_info.get("original_file_path", None) == path:
                return node_info
    return None