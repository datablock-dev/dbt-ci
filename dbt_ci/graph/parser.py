"""Module for parsing dbt manifest files and generating dependency graphs."""
import sys
import json
import logging
from typing import Literal, cast
from dbt_ci.schema import MANIFEST_KEY_MAPPING, DBTManifest, DbtNode, DependencyGraph, DependencyGraphNode, DependencyGraphNodeType, Macro, Node, Source

logger = logging.getLogger(__name__)

def skeleton_dependencies_structure():
    """Helper function to create an empty dependencies structure."""
    return {
        "node_dependencies": set(),
        "dependencies_by_type": {
            "model": set(),
            "macro": set(),
            "seed": set(),
            "snapshot": set(),
            "source": set(),
            "test": set(),
            "exposure": set(),
        },
    }

def generate_dependency_graph(manifest_file: DBTManifest) -> DependencyGraph:
    """Generate dependency graph from manifest file.
    Args:
        manifest_file: DBTManifest object representing the manifest file
    """
    child_map = manifest_file.get("child_map", {})
    dependency_graph: DependencyGraph = {
        "metadata": manifest_file.get("metadata", {}),
        "model": {},
        "seed": {},
        "snapshot": {},
        "test": {},
        "macro": {},
        "exposure": {},
        "source": {}
    }

    for key, downstream_dependencies in child_map.items():
        node_type: DependencyGraphNodeType = cast(DependencyGraphNodeType, key.split(".")[0])
        manifest_key = MANIFEST_KEY_MAPPING.get(node_type)
        full_item: DbtNode | None  = manifest_file.get(manifest_key, {}).get(key, None) if manifest_key else None

        # Skip if the node type is not recognized (e.g., "analysis", "docs", etc.)
        if node_type not in dependency_graph.keys():
            continue
        if manifest_key is None:
            print(f"Unknown node type '{node_type}' found in manifest file. Exiting.")
            sys.exit(1)
        if full_item is None:
            print(f"Item '{key}' not found in manifest file under '{manifest_key}'. Skipping.")
            continue
        
        name = full_item.get("name", None)
        compiled_code = full_item.get("compiled_code", None)
        original_file_path = full_item.get("original_file_path", None)
        config = full_item.get("config", {})

        node_type_map: dict[str, set] = {
            "model": set(),
            "macro": set(),
            "seed": set(),
            "snapshot": set(),
            "source": set(),
            "test": set(),
            "exposure": set(),
        }
            
        for dep_id in downstream_dependencies:
            dep_type = dep_id.split(".")[0]
            dep_manifest_key = MANIFEST_KEY_MAPPING.get(dep_type)
            
            if dep_manifest_key and dep_type in node_type_map:
                dep_item = manifest_file.get(dep_manifest_key, {}).get(dep_id, None)
                if dep_item:
                    dep_name = dep_item.get("name")
                    if dep_name:
                        node_type_map[dep_type].add(dep_name)

        dependency_graph[node_type][name] = {
            "name": name,
            "id": key,
            "database": full_item.get("database", None),
            "schema": full_item.get("schema", None),
            "resource_type": full_item.get("resource_type", None),
            "original_file_path": original_file_path,
            "compiled_path": full_item.get("compiled_path", None),
            "compiled_code": compiled_code,
            "config": config,
            "columns": set(full_item.get("columns", {}).keys()),
            "materialized": config.get("materialized", None),
            "incremental_strategy": config.get("incremental_strategy", None),
            "downstream_dependencies": {
                "node_dependencies": set(downstream_dependencies),
                "dependencies_by_type": {
                    "model": node_type_map["model"],
                    "macro": node_type_map["macro"],
                    "seed": node_type_map["seed"],
                    "snapshot": node_type_map["snapshot"],
                    "source": node_type_map["source"],
                    "test": node_type_map["test"],
                    "exposure": node_type_map["exposure"],
                }
            },
            "upstream_dependencies": skeleton_dependencies_structure(),
            "indirect_upstream_dependencies": skeleton_dependencies_structure(),
            "indirect_downstream_dependencies": skeleton_dependencies_structure(),
        }

        #print(full_item.get("depends_on", {}).get("macros", []))
        append_depends_on_nodes(
            dependency_graph=dependency_graph,
            node_type=node_type,
            name=name,
            dependencies=full_item.get("depends_on", {}), 
            manifest_file=manifest_file
        )

    # Macros don't appear as keys in child_map, so populate them directly from
    # the manifest's macros section so path-based lookups can find them.
    for macro_id, macro_item in manifest_file.get("macros", {}).items():
        macro_name = macro_item.get("name")
        if macro_name and macro_name not in dependency_graph["macro"]:
            dependency_graph["macro"][macro_name] = {
                "name": macro_name,
                "id": macro_id,
                "database": None,
                "schema": None,
                "resource_type": "macro",
                "original_file_path": macro_item.get("original_file_path"),
                "compiled_path": None,
                "compiled_code": None,
                "config": {},
                "columns": set(),
                "materialized": None,
                "incremental_strategy": None,
                "downstream_dependencies": skeleton_dependencies_structure(),
                "upstream_dependencies": skeleton_dependencies_structure(),
                "indirect_upstream_dependencies": skeleton_dependencies_structure(),
                "indirect_downstream_dependencies": skeleton_dependencies_structure(),
            }

    append_upstream_dependencies(dependency_graph, manifest_file)
    append_indirect_dependencies(dependency_graph, "upstream")
    append_indirect_dependencies(dependency_graph, "downstream")

    return dependency_graph

def append_depends_on_nodes(
    dependency_graph: DependencyGraph,
    node_type: DependencyGraphNodeType,
    name: str,
    dependencies: dict[DependencyGraphNodeType, list[str]], 
    manifest_file: DBTManifest
) -> None:
    """Append dependencies from the "depends_on" section of the manifest file to the dependency graph."""
    for dep_type, dep_ids in dependencies.items():
        if dep_ids is None or not isinstance(dep_ids, list):
            continue

        # Add all dep_ids to node_dependencies
        dependency_graph[node_type][name]["upstream_dependencies"]["node_dependencies"].update(dep_ids)
        
        # Retrieve name from manifest
        for dep_id in dep_ids:
            # dep_type from depends_on is "nodes" or "macros"
            # Look up in the correct manifest section
            manifest_section = "macros" if dep_type == "macros" else "nodes"
            node = manifest_file.get(manifest_section, {}).get(dep_id, None)
            
            if node is None:
                continue
                
            node_name = node.get("name")
            if node_name is None:
                continue

            # Map to the correct dependency type
            # For "macros" -> "macro", for "nodes" -> extract from dep_id
            if dep_type == "macros":
                dep_category = "macro"
            else:
                # Extract actual type from dep_id (e.g., "model.project.name" -> "model")
                dep_category = dep_id.split(".")[0]
            
            # Only add if this category is tracked
            if dep_category in dependency_graph[node_type][name]["upstream_dependencies"]["dependencies_by_type"]:
                dependency_graph[node_type][name]["upstream_dependencies"]["dependencies_by_type"][dep_category].add(node_name)

def output_dependency_graph(dependency_graph: DependencyGraph, output_path: str) -> None:
    """Output the dependency graph to a JSON file."""
    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(
            obj=dependency_graph, 
            fp=file, 
            indent=4, 
            default=lambda o: list(o) if isinstance(o, set) else o
        )

def index_nodes_by_id(dependency_graph: DependencyGraph) -> dict[str, DependencyGraphNode]:
    """Build an id -> node lookup so dependency resolution doesn't rescan the graph."""
    index: dict[str, DependencyGraphNode] = {}
    for node_type, nodes in dependency_graph.items():
        if node_type == "metadata":
            continue
        for node_data in cast(dict, nodes).values():
            node_id = node_data.get("id")
            if node_id:
                index[node_id] = node_data
    return index


def compute_transitive_closure(
    node_id: str,
    adjacency: dict[str, set[str]],
    memo: dict[str, set[str]],
) -> set[str]:
    """
    Return every node reachable from node_id, memoising the result for reuse.

    Walks the graph iteratively with an explicit stack rather than recursing: dbt DAGs
    can be deep enough to exhaust the interpreter's recursion limit, and every node's
    closure is needed, so memoising turns the whole pass from quadratic into linear in
    the number of edges. Nodes currently being expanded are tracked so a cyclic manifest
    terminates instead of looping forever.
    """
    if node_id in memo:
        return memo[node_id]

    expanding: set[str] = set()
    stack: list[tuple[str, bool]] = [(node_id, False)]

    while stack:
        current, is_expanded = stack.pop()

        if is_expanded:
            reachable: set[str] = set()
            for dependency in adjacency.get(current, ()):
                reachable.add(dependency)
                reachable.update(memo.get(dependency, ()))
            memo[current] = reachable
            expanding.discard(current)
            continue

        if current in memo or current in expanding:
            continue

        expanding.add(current)
        stack.append((current, True))
        for dependency in adjacency.get(current, ()):
            if dependency not in memo and dependency not in expanding:
                stack.append((dependency, False))

    return memo.get(node_id, set())


def append_upstream_dependencies(dependency_graph: DependencyGraph, manifest_file: DBTManifest) -> None:
    """Populate upstream dependencies by reversing downstream dependencies"""
    # Iterate through all nodes and their downstream dependencies
    parent_map = manifest_file.get("parent_map", {})

    for child_id, parent_ids in parent_map.items():
        if len(parent_ids) == 0:
            continue

        child_node_type = child_id.split(".")[0]
        manifest_key = MANIFEST_KEY_MAPPING.get(child_node_type)
        if manifest_key is None:
            logger.error(f"Unknown node type '{child_node_type}' found in manifest file. Skipping.")
            sys.exit(1)
        
        node = manifest_file.get(manifest_key, {}).get(child_id, {}).get("name", None)

        if node is None:
            print(f"Node with ID '{child_id}' not found in manifest file under '{manifest_key}'. Skipping.")
            continue

        dependency_graph[child_node_type][node]["upstream_dependencies"]["node_dependencies"].update(parent_ids)

        # Sort by dependency type
        for parent_id in parent_ids:
            parent_node_type = parent_id.split(".")[0]
            manifest_key = MANIFEST_KEY_MAPPING.get(parent_node_type)
            parent_node = manifest_file.get(manifest_key, {}).get(parent_id, None)
            name = parent_node.get("name", None) if parent_node else None

            if name is None:
                print(f"Parent node with ID '{parent_id}' not found in manifest file under '{manifest_key}'. Skipping.")
                continue

            dependency_graph[child_node_type][node]["upstream_dependencies"]["dependencies_by_type"][parent_node_type].add(name)


def append_indirect_dependencies(dependency_graph, direction: Literal["upstream", "downstream"] = "upstream"):
    """Populate indirect dependencies (the full transitive closure, including direct ones)

    Args:
        dependency_graph: The lineage map to populate
        direction: Either "upstream" or "downstream"
    """
    direct_key = f"{direction}_dependencies"
    indirect_key = f"indirect_{direction}_dependencies"

    nodes_by_id = index_nodes_by_id(dependency_graph)
    adjacency: dict[str, set[str]] = {
        node_id: set(node_data[direct_key]["node_dependencies"])
        for node_id, node_data in nodes_by_id.items()
    }
    memo: dict[str, set[str]] = {}

    for node_type, nodes in dependency_graph.items():
        if node_type == "metadata":  # Skip metadata
            continue
        for node_data in nodes.values():
            node_id = node_data.get("id")
            all_indirect = (
                compute_transitive_closure(node_id, adjacency, memo)
                if node_id
                else set()
            )

            node_data[indirect_key]["node_dependencies"] = set(all_indirect)

            # Populate by type
            for indirect_id in all_indirect:
                indirect_node = nodes_by_id.get(indirect_id)
                if indirect_node:
                    indirect_type = indirect_id.split(".")[0]
                    # Only add to dependencies_by_type if the indirect_type is tracked
                    if indirect_type in node_data[indirect_key]["dependencies_by_type"]:
                        node_data[indirect_key]["dependencies_by_type"][indirect_type].add(indirect_node["name"])