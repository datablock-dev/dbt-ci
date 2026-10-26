"""Module for parsing dbt manifest files and generating dependency graphs."""

import logging
from collections.abc import Mapping
from typing import Any, cast
from dbt_ci.errors import ManifestError
from dbt_ci.schema import (
    MANIFEST_KEY_MAPPING,
    DBTManifest,
    DependencyGraph,
    DependencyGraphNodeType,
)

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
            "unit_test": set(),
        },
    }


def normalize_node_ids(entries) -> list[str]:
    """Return the unique_ids in a manifest dependency list, whatever shape each entry has.

    dbt-core writes plain unique_id strings. Manifests written by dbt v2 can also hold
    pairs such as ``[unique_id, location]`` or objects carrying ``unique_id``; those are
    reduced to the id, and anything without a recognisable id is dropped.
    """
    if not isinstance(entries, (list, tuple, set)):
        return []
    node_ids: list[str] = []
    for entry in entries:
        if isinstance(entry, str):
            node_ids.append(entry)
        elif isinstance(entry, (list, tuple)) and entry and isinstance(entry[0], str):
            node_ids.append(entry[0])
        elif isinstance(entry, dict):
            node_id = entry.get("unique_id") or entry.get("id")
            if isinstance(node_id, str):
                node_ids.append(node_id)
    return node_ids


def column_names(columns) -> set[str]:
    """Return column names from a manifest ``columns`` field, given as a mapping or a list."""
    if isinstance(columns, dict):
        return {name for name in columns.keys() if isinstance(name, str)}
    if isinstance(columns, list):
        return {
            column["name"]
            for column in columns
            if isinstance(column, dict) and isinstance(column.get("name"), str)
        }
    return set()


def generate_dependency_graph(manifest_file: DBTManifest) -> DependencyGraph:
    """
    Build the dependency graph of a manifest.

    Every entry is read defensively, as a plain mapping: manifests differ between dbt
    versions, and dbt v2 writes some fields in other shapes than dbt-core does.
    """
    manifest = cast(dict[str, Any], manifest_file)
    child_map = manifest.get("child_map") or {}
    dependency_graph: DependencyGraph = {
        "model": {},
        "seed": {},
        "snapshot": {},
        "test": {},
        "macro": {},
        "exposure": {},
        "source": {},
        "unit_test": {},
    }

    for key, raw_downstream_dependencies in child_map.items():
        downstream_dependencies = normalize_node_ids(raw_downstream_dependencies)
        node_type: DependencyGraphNodeType = cast(DependencyGraphNodeType, key.split(".")[0])
        manifest_key = MANIFEST_KEY_MAPPING.get(node_type)
        full_item: dict[str, Any] | None = (
            (manifest.get(manifest_key) or {}).get(key, None) if manifest_key else None
        )

        # Skip if the node type is not recognized (e.g., "analysis", "docs", etc.)
        if node_type not in dependency_graph.keys():
            continue
        if manifest_key is None:
            raise ManifestError(f"Unknown node type '{node_type}' found in the manifest.")
        if full_item is None:
            logger.debug(
                f"Item '{key}' not found in manifest file under '{manifest_key}'. Skipping."
            )
            continue

        name = full_item.get("name") or key.split(".")[-1]
        compiled_code = full_item.get("compiled_code")
        original_file_path = full_item.get("original_file_path")
        config = full_item.get("config", {})

        node_type_map: dict[str, set] = {
            "model": set(),
            "macro": set(),
            "seed": set(),
            "snapshot": set(),
            "source": set(),
            "test": set(),
            "exposure": set(),
            "unit_test": set(),
        }

        for dep_id in downstream_dependencies:
            dep_type = dep_id.split(".")[0]
            if dep_type in node_type_map:
                node_type_map[dep_type].add(dep_id)

        dependency_graph[node_type][key] = {
            "name": name,
            "id": key,
            "fqn": full_item.get("fqn"),
            "database": full_item.get("database"),
            "schema": full_item.get("schema"),
            # The relation name dbt resolved, including custom generate_alias_name macros
            "alias": full_item.get("alias"),
            "resource_type": full_item.get("resource_type") or node_type,
            "original_file_path": original_file_path,
            "patch_path": normalize_patch_path(full_item.get("patch_path", None)),
            "compiled_path": full_item.get("compiled_path"),
            "compiled_code": compiled_code,
            "config": config,
            "columns": column_names(full_item.get("columns")),
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
                    "unit_test": node_type_map["unit_test"],
                },
            },
            "upstream_dependencies": skeleton_dependencies_structure(),
        }

        append_depends_on_nodes(
            dependency_graph=dependency_graph,
            node_type=node_type,
            node_id=key,
            dependencies=full_item.get("depends_on") or {},
        )

    # Macros don't appear as keys in child_map, so populate them directly from
    # the manifest's macros section so path-based lookups can find them.
    for macro_id, macro_item in (manifest.get("macros") or {}).items():
        macro_name = macro_item.get("name")
        if macro_name and macro_id not in dependency_graph["macro"]:
            dependency_graph["macro"][macro_id] = {
                "name": macro_name,
                "id": macro_id,
                "fqn": macro_item.get("fqn", None),
                "database": None,
                "schema": None,
                "alias": None,
                "resource_type": "macro",
                "original_file_path": macro_item.get("original_file_path"),
                "patch_path": None,
                "compiled_path": None,
                "compiled_code": None,
                "config": {},
                "columns": set(),
                "materialized": None,
                "incremental_strategy": None,
                "downstream_dependencies": skeleton_dependencies_structure(),
                "upstream_dependencies": skeleton_dependencies_structure(),
            }
            # Macros calling other macros, so a change to a shared macro reaches every
            # node that uses it indirectly (see get_nodes_using_macros).
            append_depends_on_nodes(
                dependency_graph=dependency_graph,
                node_type="macro",
                node_id=macro_id,
                dependencies=macro_item.get("depends_on") or {},
            )

    append_upstream_dependencies(dependency_graph, manifest_file)

    return dependency_graph


def normalize_patch_path(patch_path: str | None) -> str | None:
    """
    Strip the package prefix from a node's patch_path.

    dbt records the YAML file that configures a node as "<package>://models/schema.yml",
    whereas git reports the same file as "models/schema.yml" relative to the project.
    """
    if not patch_path:
        return None
    return patch_path.split("://", 1)[-1]


def append_depends_on_nodes(
    dependency_graph: DependencyGraph,
    node_type: DependencyGraphNodeType,
    node_id: str,
    dependencies: Mapping[str, Any],
) -> None:
    """Append dependencies from the "depends_on" section of the manifest file to the dependency graph."""
    upstream = dependency_graph[node_type][node_id]["upstream_dependencies"]

    # Only "nodes" and "macros" hold dependency ids. dbt v2 adds further keys under
    # depends_on (e.g. per-reference locations) that must not be read as ids.
    for dep_type in ("nodes", "macros"):
        dep_ids = normalize_node_ids(dependencies.get(dep_type))
        if not dep_ids:
            continue

        # Add all dep_ids to node_dependencies
        upstream["node_dependencies"].update(dep_ids)

        for dep_id in dep_ids:
            # dep_type from depends_on is "nodes" or "macros"; for nodes the actual
            # resource type is the first segment of the unique_id
            # (e.g. "model.project.name" -> "model").
            dep_category = "macro" if dep_type == "macros" else dep_id.split(".")[0]

            # Only add if this category is tracked
            if dep_category in upstream["dependencies_by_type"]:
                upstream["dependencies_by_type"][dep_category].add(dep_id)


def append_upstream_dependencies(
    dependency_graph: DependencyGraph, manifest_file: DBTManifest
) -> None:
    """Populate upstream dependencies from the manifest's parent_map."""
    parent_map = manifest_file.get("parent_map") or {}

    for child_id, raw_parent_ids in parent_map.items():
        parent_ids = normalize_node_ids(raw_parent_ids)
        if len(parent_ids) == 0:
            continue

        child_node_type = child_id.split(".")[0]
        node = dependency_graph.get(child_node_type, {}).get(child_id)

        if node is None:
            # Resource types dbt-ci doesn't track (analyses, operations, unit tests)
            # legitimately appear in parent_map without being graph nodes.
            logger.debug(f"Node '{child_id}' is not tracked in the dependency graph. Skipping.")
            continue

        upstream = node["upstream_dependencies"]
        upstream["node_dependencies"].update(parent_ids)

        # Sort by dependency type
        for parent_id in parent_ids:
            parent_node_type = parent_id.split(".")[0]
            if parent_node_type in upstream["dependencies_by_type"]:
                upstream["dependencies_by_type"][parent_node_type].add(parent_id)
