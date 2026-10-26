"""
Ephemeral command for dbt-ci

Models: By default, select all downstream dependencies (full graph)
Tests: By default, select upstream depedendenceis (1 level)
Snapshots: By default, only select upstream dependencies (1 level)
"""

import sys
import logging
from argparse import Namespace
from typing import Optional, cast
import click
from dbt_ci.utilities.cache import CacheManager
from dbt_ci.dbt.flags import apply_cached_config
from dbt_ci.graph.dependency_graph import DbtGraph
from dbt_ci.graph.parser import generate_dependency_graph
from dbt_ci.utilities.logging import print_exception, redact_namespace
from dbt_ci.schema import DependencyGraph, EphemeralMapNode, NodeConfig, StateChangeSummary
from dbt_ci.commands.ephemeral.clone import clone_command
from dbt_ci.utilities.paths import get_manifest_file
from dbt_ci.graph.graph_utils import (
    get_node_ids_from_structured_nodes,
    get_nodes,
    get_relation_name,
)

logger = logging.getLogger(__name__)


def ephemeral(args: Namespace):
    """Run ephemeral CI check workflow

    Detects changes, lists modified models, but doesn't execute them.
    Useful for quick CI checks and PR previews.

    Examples:
        dbt-ci ephemeral --state prod-manifest/ --dbt-project-dir ./dbt
        dbt-ci ephemeral --state prod-manifest/ --runner docker

        # With environment variables
        export DBT_STATE=./dbt/.dbtstate/
        export DBT_PROJECT_DIR=./dbt
        dbt-ci ephemeral
    """
    try:
        # Convert kwargs to Namespace and resolve configuration
        # Variables class handles type conversions (tuples->lists, string->bool, etc.)
        click.secho("DBT CI Ephemeral", fg="green", bold=True)
        logger.debug(f"Running with the following arguments: {redact_namespace(args)}")
        if getattr(args, "keep_env", False):
            logger.warning(
                "--keep-env is deprecated and has no effect: ephemeral never destroys the "
                "environment it creates. Use 'dbt-ci finalize --clean-ephemeral' to tear it down."
            )
        cache = CacheManager(args)
        cache.start_report("ephemeral", args)
        apply_cached_config(args)
        cache_dict: StateChangeSummary = cast(StateChangeSummary, cache.get_cache())

        if cache_dict is None:
            logger.error(
                "No cache found, please run 'dbt-ci init' first to generate the necessary manifest files and cache for comparison."
            )
            sys.exit(1)

        logger.info("Cache successfully found - using cached state for comparison")
        changed_nodes_dict = {
            "modified_nodes": get_node_ids_from_structured_nodes(
                cache_dict.get("modified_nodes", None)
            )
            or [],
            "deleted_nodes": get_node_ids_from_structured_nodes(
                cache_dict.get("deleted_nodes", None)
            )
            or [],
            "new_nodes": get_node_ids_from_structured_nodes(cache_dict.get("new_nodes", None))
            or [],
        }

        cloned_nodes = clone_command(changed_nodes_dict, args)
        if cloned_nodes is None:
            sys.exit(0)

        # Store the ephemeral map so `finalize --clean-ephemeral` knows which datasets to drop
        ephemeral_map = build_ephemeral_map(args, cloned_nodes)
        cache.write_ephemeral(ephemeral_map)
        cache.update_report("ephemeral", "completed", comment=str(list(ephemeral_map.keys())))
        logger.info("Ephemeral strategy completed successfully.")
        logger.info(
            "Now you can run your dbt command with the appropriate selection to target the ephemeral models and their downstream dependencies."
        )
        sys.exit(0)
    except Exception as e:
        cache = CacheManager(args)
        cache.update_report("ephemeral", "failed", comment=str(e))
        print_exception(e, "Ephemeral environment failed")
        sys.exit(1)


def get_clone_graph(args: Namespace) -> DependencyGraph:
    """
    Return the dependency graph of the manifest `dbt clone` just wrote.

    That manifest is compiled for the target the clone ran against, so it says where the
    cloned relations really are. The cached target manifest is compiled against the
    reference target, which on warehouses where CI and production differ by target (a
    separate CI schema) points at production instead, and teardown would then refuse to
    drop anything. Falls back to the cached manifest when dbt wrote none on this host.
    """
    try:
        return generate_dependency_graph(
            get_manifest_file(getattr(args, "dbt_project_dir", None) or ".")
        )
    except FileNotFoundError:
        logger.debug(
            "No manifest from dbt clone found; using the cached target manifest for the ephemeral map."
        )
        return DbtGraph(args).to_dict()


def build_ephemeral_map(args: Namespace, node_ids: list[str]) -> dict[str, EphemeralMapNode]:
    """Map each cloned model and snapshot to its ephemeral (target) and reference relation."""
    target_graph = get_clone_graph(args)
    reference_graph = DbtGraph(args, is_reference=True).to_dict()
    target_nodes = get_nodes(target_graph, node_ids) or {}
    reference_nodes = get_nodes(reference_graph, node_ids) or {}

    ephemeral_map: dict[str, EphemeralMapNode] = {}
    for node_id, target_node in target_nodes.items():
        # Ephemeral models are never materialised, so they have no relation to clean up
        if target_node.get("materialized") == "ephemeral":
            continue
        reference_node = reference_nodes.get(node_id)
        ephemeral_map[node_id] = {
            "name": target_node["name"],
            "resource_type": target_node["resource_type"],
            "ephemeral_config": full_config_or_none(
                database=target_node.get("database", None),
                schema=target_node.get("schema", None),
                name=target_node.get("name", None),
                alias=get_relation_name(target_node),
            ),
            "reference_config": (
                full_config_or_none(
                    database=reference_node.get("database", None),
                    schema=reference_node.get("schema", None),
                    name=reference_node.get("name", None),
                    alias=get_relation_name(reference_node),
                )
                if reference_node
                else None
            ),
        }
    return ephemeral_map


def full_config_or_none(
    database: Optional[str], schema: Optional[str], name: Optional[str], alias: Optional[str] = None
) -> NodeConfig | None:
    """Helper function to return full config dict if all values are present, otherwise None."""
    if any(v is None for v in (database, schema, name)):
        return None
    return {
        "database": database,
        "schema": schema,
        "name": name,
        "alias": alias,
    }
