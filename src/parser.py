import sys
import json
import os
from typing import Dict, List, Set, Any
from src.paths import get_manifest_file
from src.schema import DBTManifest, DependencyGraph, DependencyGraphNodeType

manifest_key_mapping = {
    "model": "nodes",
    "seed": "nodes",
    "snapshot": "nodes",
    "test": "nodes",
    "macro": "macros",
    "exposure": "exposures",
    "source": "sources"
}

def skeleton_dependencies_structure():
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

def generate_dependency_graph(manifest_file_path: str) -> DependencyGraph:
    manifest_file = get_manifest_file(manifest_file_path)
    child_map = manifest_file.get("child_map", {})

    metadata = manifest_file.get("metadata")
    if metadata is None:
        metadata = {}

    dependency_graph: DependencyGraph = {
        "metadata": metadata,
        "model": {},
        "seed": {},
        "snapshot": {},
        "test": {},
        "macro": {},
        "exposure": {},
        "source": {}
    }

    for key, downstream_dependencies in child_map.items():
        node_type: DependencyGraphNodeType = key.split(".")[0]
        manifest_key = manifest_key_mapping.get(node_type)
        full_item = manifest_file.get(manifest_key, {}).get(key, None) if manifest_key else None

        # Skip if the node type is not recognized (e.g., "analysis", "docs", etc.)
        if node_type not in dependency_graph.keys():
            continue
        elif manifest_key is None:
            print(f"Unknown node type '{node_type}' found in manifest file. Exiting.")
            sys.exit(1)
        elif full_item is None:
            print(f"Item '{key}' not found in manifest file under '{manifest_key}'. Skipping.")
            continue
        
        name = full_item.get("name", None)
        compiled_code = full_item.get("compiled_code", None)
        original_file_path = full_item.get("original_file_path", None)

        #if node_type == "seed" and original_file_path:
        #    compiled_code = parse_seed_file(
        #        manifest_file_path=manifest_file_path, 
        #        seed_file_path=original_file_path
        #    )

        node_type_map: Dict[str, set] = {
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
            dep_manifest_key = manifest_key_mapping.get(dep_type)
            
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
            "columns": set(full_item.get("columns", {}).keys()),
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

    append_upstream_dependencies(dependency_graph, manifest_file)
    append_indirect_dependencies(dependency_graph, "upstream")
    append_indirect_dependencies(dependency_graph, "downstream")

    return dependency_graph

def append_depends_on_nodes(
    dependency_graph: DependencyGraph,
    node_type: DependencyGraphNodeType,
    name: str,
    dependencies: Dict[DependencyGraphNodeType, List[str]], 
    manifest_file: DBTManifest
) -> None:
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
    with open(output_path, "w") as file:
        json.dump(
            obj=dependency_graph, 
            fp=file, 
            indent=4, 
            default=lambda o: list(o) if isinstance(o, set) else o
        )

def find_node_by_id(dependency_graph, node_id):
    """Find a node in dependency_graph by its ID"""
    node_type = node_id.split(".")[0]
    if node_type in dependency_graph:
        for node_data in dependency_graph[node_type].values():
            if node_data.get("id") == node_id:
                return node_data
    return None


def collect_dependencies_recursively(dependency_graph, node_data, visited, direction="upstream"):
    """Recursively collect upstream or downstream dependencies"""
    dep_key = "upstream_dependencies" if direction == "upstream" else "downstream_dependencies"
    
    for dep_id in node_data[dep_key]["node_dependencies"]:
        if dep_id not in visited:
            visited.add(dep_id)
            dep_node = find_node_by_id(dependency_graph, dep_id)
            if dep_node:
                collect_dependencies_recursively(dependency_graph, dep_node, visited, direction)


def append_upstream_dependencies(dependency_graph, manifest_file):
    """Populate upstream dependencies by reversing downstream dependencies"""
    # Iterate through all nodes and their downstream dependencies
    parent_map = manifest_file.get("parent_map", {})

    for child_id, parent_ids in parent_map.items():
        if len(parent_ids) == 0:
            continue

        child_node_type = child_id.split(".")[0]
        manifest_key = manifest_key_mapping.get(child_node_type)
        node = manifest_file.get(manifest_key, {}).get(child_id, None).get("name", None)

        if node is None:
            print(f"Node with ID '{child_id}' not found in manifest file under '{manifest_key}'. Skipping.")
            continue

        dependency_graph[child_node_type][node]["upstream_dependencies"]["node_dependencies"].update(parent_ids)

        # Sort by dependency type
        for parent_id in parent_ids:
            parent_node_type = parent_id.split(".")[0]
            manifest_key = manifest_key_mapping.get(parent_node_type)
            parent_node = manifest_file.get(manifest_key, {}).get(parent_id, None)
            name = parent_node.get("name", None) if parent_node else None

            if name is None:
                print(f"Parent node with ID '{parent_id}' not found in manifest file under '{manifest_key}'. Skipping.")
                continue

            dependency_graph[child_node_type][node]["upstream_dependencies"]["dependencies_by_type"][parent_node_type].add(name)


def append_indirect_dependencies(dependency_graph, direction="upstream"):
    """Populate indirect dependencies (transitive, excluding direct)
    
    Args:
        dependency_graph: The lineage map to populate
        direction: Either "upstream" or "downstream"
    """
    direct_key = f"{direction}_dependencies"
    indirect_key = f"indirect_{direction}_dependencies"
    
    for node_type, nodes in dependency_graph.items():
        if node_type == "metadata":  # Skip metadata
            continue
        for node_data in nodes.values():
            # Collect all transitive dependencies
            all_indirect = set()
            for direct_dep_id in node_data[direct_key]["node_dependencies"]:
                dep_node = find_node_by_id(dependency_graph, direct_dep_id)
                if dep_node:
                    collect_dependencies_recursively(dependency_graph, dep_node, all_indirect, direction)
            
            # Store indirect dependencies (excluding direct)
            node_data[indirect_key]["node_dependencies"] = all_indirect
            
            # Populate by type
            for indirect_id in all_indirect:
                indirect_node = find_node_by_id(dependency_graph, indirect_id)
                if indirect_node:
                    indirect_type = indirect_id.split(".")[0]
                    # Only add to dependencies_by_type if the indirect_type is tracked
                    if indirect_type in node_data[indirect_key]["dependencies_by_type"]:
                        node_data[indirect_key]["dependencies_by_type"][indirect_type].add(indirect_node["name"])

"""
def parse_seed_file(manifest_file_path: str, seed_file_path: str) -> str:
    extensions = ['.csv'] # Expand if needed
    dbt_root_path = get_root_path_from_manifest_file_path(manifest_file_path)
    adjusted_seed_file_path = os.path.join(dbt_root_path, seed_file_path)

    # Check that file exists
    if not os.path.exists(adjusted_seed_file_path):
        print(f"Seed file not found at {adjusted_seed_file_path}")
        sys.exit(1)

    with open(adjusted_seed_file_path, 'r') as file:        
        # For simplicity, just read the content
        content = file.read()
        return content
"""
        
if __name__ == "__main__":
    # Example usage - update path to your manifest file
    manifest_path = "dbt/target/manifest.json"
    generate_dependency_graph(manifest_path)
        