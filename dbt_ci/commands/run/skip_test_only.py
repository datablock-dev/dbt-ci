"""
Find changed nodes whose only change is to their tests, so `run` can skip rebuilding them.

A model's data tests live in its YAML properties file. The git comparison strategy marks
every node configured in a changed YAML file as modified, and the hybrid strategy keeps a
model dbt flags (for example for environment-specific config) when its YAML file changed.
Either way, editing one test can rebuild a model and everything downstream of it. With
`run --skip-test-only-changes`, a node is left out of the build when nothing that defines
it changed apart from its tests; the changed tests themselves still run.
"""

import logging
import os
from argparse import Namespace
from typing import Any

import yaml

from dbt_ci.graph.graph_utils import get_node, get_nodes_using_macros
from dbt_ci.schema import DependencyGraph
from dbt_ci.utilities.git import GitAdapter

logger = logging.getLogger(__name__)

# The YAML section each buildable resource type is configured under
YAML_SECTIONS: dict[str, str] = {
    "model": "models",
    "seed": "seeds",
    "snapshot": "snapshots",
}

# Keys that declare data tests, at the resource, column and model-version level
TEST_KEYS = ("tests", "data_tests")

# Project-level files that can change every node's config or macros without touching the
# node's own files. When one of them changed, no node is treated as test-only.
PROJECT_FILES = {"dbt_project.yml", "packages.yml", "dependencies.yml", "package-lock.yml"}


def find_test_only_changes(
    args: Namespace, dependency_graph: DependencyGraph, node_ids: list[str]
) -> set[str]:
    """
    Return the given modified nodes whose definition changed only in their tests.

    A node qualifies when its own file (the .sql, .py or .csv) is unchanged, no macro it
    uses changed, its YAML properties file changed, and its entry in that file is the same
    as on the base branch once its tests are removed. Anything that cannot be confirmed
    keeps the node in the build, so the option never skips a node that really changed.
    """
    candidates = [node_id for node_id in node_ids if node_id.split(".")[0] in YAML_SECTIONS]
    if not candidates:
        return set()

    try:
        git = GitAdapter(args)
        changed_files = git.get_changed_files()
    except Exception as e:
        logger.warning(
            f"--skip-test-only-changes needs the git diff, which failed ({e}); "
            "building every changed node."
        )
        return set()

    changed_paths = {path for paths in changed_files.values() for path in paths}
    changed_project_files = sorted(changed_paths & PROJECT_FILES)
    if changed_project_files:
        logger.info(
            f"{', '.join(changed_project_files)} changed, which can change any node's config; "
            "--skip-test-only-changes is building every changed node."
        )
        return set()

    changed_macros = {
        macro_id
        for macro_id, macro in (dependency_graph.get("macro") or {}).items()
        if macro.get("original_file_path") in changed_paths
    }
    macro_users = get_nodes_using_macros(dependency_graph, changed_macros)

    # Each properties file is read and parsed once, however many nodes it configures
    documents: dict[tuple[str, str], Any] = {}

    def load(path: str, revision: str) -> Any:
        """Parse a YAML file at the base or in the working tree, caching the result."""
        key = (path, revision)
        if key not in documents:
            if revision == "base":
                text = git.read_base_file(path)
            else:
                text = read_working_file(args, path)
            documents[key] = parse_yaml(text)
        return documents[key]

    test_only: set[str] = set()
    for node_id in candidates:
        node = get_node(dependency_graph, node_id)
        if node is None or node_id in macro_users:
            continue
        if node.get("original_file_path") in changed_paths:
            continue
        patch_path = node.get("patch_path")
        if not patch_path or patch_path not in changed_paths:
            # Nothing in the diff explains the change, so it isn't a test edit
            continue

        section = YAML_SECTIONS[node_id.split(".")[0]]
        name = node.get("name")
        before = find_entry(load(patch_path, "base"), section, name)
        after = find_entry(load(patch_path, "head"), section, name)
        if before is None or after is None:
            # Moved between files, or the file could not be read: treat as a real change
            continue
        if without_tests(before) == without_tests(after):
            test_only.add(node_id)

    return test_only


def read_working_file(args: Namespace, project_path: str) -> str | None:
    """Return a project file from the working tree, or None when it cannot be read."""
    path = os.path.join(getattr(args, "dbt_project_dir", None) or ".", project_path)
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError as e:
        logger.debug(f"Could not read '{path}': {e}")
        return None


def parse_yaml(text: str | None) -> Any:
    """Parse a YAML document, returning None when it is missing or invalid."""
    if text is None:
        return None
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        logger.debug(f"Could not parse YAML: {e}")
        return None


def find_entry(document: Any, section: str, name: str | None) -> dict[str, Any] | None:
    """Return the entry for a named resource under a section of a properties file."""
    if not isinstance(document, dict) or not name:
        return None
    for entry in document.get(section) or []:
        if isinstance(entry, dict) and entry.get("name") == name:
            return entry
    return None


def without_tests(entry: dict[str, Any]) -> dict[str, Any]:
    """Return a properties entry with its data tests removed, including on columns and versions."""
    stripped = {key: value for key, value in entry.items() if key not in TEST_KEYS}
    for key in ("columns", "versions"):
        items = stripped.get(key)
        if isinstance(items, list):
            stripped[key] = [
                without_tests(item) if isinstance(item, dict) else item for item in items
            ]
    return stripped
