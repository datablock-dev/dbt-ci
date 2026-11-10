"""
Find the nodes whose config changed through dbt_project.yml.

A config set in dbt_project.yml (e.g. `models: {project: {+materialized: table}}`)
changes nodes whose own files git never saw change, so the git and hybrid strategies
missed them. The file's resource sections are compared with their version at the merge
base to see which config keys changed; nodes whose config differs from the reference in
one of those keys changed through it. Limiting the comparison to those keys keeps out
nodes that only differ from the reference through environment-specific config, which the
hybrid strategy exists to leave out.
"""

import logging
from typing import Any

import yaml

from dbt_ci.commands.init.reasons import changed_config_keys
from dbt_ci.graph.graph_utils import get_node
from dbt_ci.schema import DependencyGraph

logger = logging.getLogger(__name__)

PROJECT_FILE = "dbt_project.yml"
# Package files: a version change alters macros git cannot map to the nodes using them
PACKAGE_FILES = ("packages.yml", "dependencies.yml", "package-lock.yml")
# dbt_project.yml sections whose (nested) keys configure nodes
RESOURCE_SECTIONS = ("models", "seeds", "snapshots", "tests", "data_tests")
# Node types those configs end up on
NODE_TYPES = ("model", "seed", "snapshot", "test")


def changed_project_config_keys(base_text: str | None, head_text: str | None) -> set[str]:
    """
    Return the config keys (without '+') whose value changed in dbt_project.yml.

    Each resource section is a tree of folders ending in config values; a key starting
    with '+' is always a config, even when its value is a mapping (e.g. +meta). Values
    are compared per folder path, so moving a config between folders counts as a change.
    """
    before = _config_leaves(_load(base_text))
    after = _config_leaves(_load(head_text))
    return {path[-1] for path in set(before) | set(after) if before.get(path) != after.get(path)}


def nodes_with_project_config_change(
    keys: set[str], target_graph: DependencyGraph, reference_graph: DependencyGraph
) -> dict[str, list[str]]:
    """Return the nodes whose config differs from the reference in one of the keys."""
    found: dict[str, list[str]] = {}
    if not keys:
        return found
    for node_type in NODE_TYPES:
        for node_id, target in (target_graph.get(node_type) or {}).items():
            reference = get_node(reference_graph, node_id)
            if reference is None:
                continue
            changed = sorted(set(changed_config_keys(reference, target)) & keys)
            if changed:
                found[node_id] = changed
    return found


def project_config_reason(keys: list[str]) -> str:
    """Describe a config change made in dbt_project.yml as the reason for a node."""
    return f"config in `{PROJECT_FILE}` changed: " + ", ".join(f"`{key}`" for key in keys)


def _load(text: str | None) -> dict[str, Any]:
    """Parse dbt_project.yml, treating a missing or invalid file as empty."""
    if not text:
        return {}
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as e:
        logger.debug(f"Could not parse {PROJECT_FILE}: {e}")
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _config_leaves(project: dict[str, Any]) -> dict[tuple[str, ...], Any]:
    """Flatten the resource sections into {(section, folder..., config key): value}."""
    leaves: dict[tuple[str, ...], Any] = {}

    def walk(node: Any, path: tuple[str, ...]) -> None:
        """Record config values below a folder, recursing into sub-folders."""
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            name = str(key)
            if name.startswith("+"):
                leaves[(*path, name[1:])] = value
            elif isinstance(value, dict):
                walk(value, (*path, name))
            else:
                leaves[(*path, name)] = value

    for section in RESOURCE_SECTIONS:
        walk(project.get(section), (section,))
    return leaves
