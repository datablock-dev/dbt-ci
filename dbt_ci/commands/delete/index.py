"""
    Delete command for dbt-ci
"""

import sys
import logging
from typing import cast
from argparse import Namespace
import click
from dbt_ci.utilities.cache import CacheManager
from dbt_ci.dbt.flags import apply_cached_config
from dbt_ci.utilities.logging import redact_namespace
from dbt_ci.connectors import get_connector
from dbt_ci.graph.dependency_graph import DbtGraph
from dbt_ci.schema import DeleteMapNode, DependencyGraph, DependencyGraphNode, SupportedConnectors
from dbt_ci.graph.graph_utils import get_node, get_node_ids_from_structured_nodes, get_nodes, get_relation_name
from dbt_ci.utilities.paths import get_profile

logger = logging.getLogger(__name__)

def delete(args: Namespace):
    """Delete deleted dbt models"""
    try:
        click.secho("DBT CI Delete", fg="green", bold=True)
        logger.debug(f"Running with the following arguments: {redact_namespace(args)}")
        cache = CacheManager(args)
        cache.start_report("delete", args)
        apply_cached_config(args)
        connector_type = cast(SupportedConnectors, get_profile(args)["type"])
        delete_connector = get_connector(connector_type)
        delete_map = generate_delete_map(args, cache)

        if delete_connector is None:
            logger.error(f"Connector '{connector_type}' does not support delete strategy, which is required for delete command.")
            sys.exit(1)

        delete_function = delete_connector.get("strategies", {}).get("delete", None)
        if delete_function is None:
            logger.error(f"Connector '{connector_type}' does not have a delete strategy implemented, which is required for delete command.")
            sys.exit(1)

        if len(delete_map) == 0:
            logger.info("No nodes to delete. Exiting...")
            sys.exit(0)

        logger.info("\n------------------------------------------------------")
        click.secho(f"Nodes to be deleted ({len(delete_map)})", fg="green", bold=True)
        for node in delete_map.values():
            logger.info(f"  • {node['table_id']}")
        logger.info("------------------------------------------------------\n")

        if getattr(args, "dry_run", False):
            logger.info("\nDry run complete - no nodes were actually deleted.")
            sys.exit(0)

        delete_function(delete_map, args)
        cache.update_report("delete", "completed", comment=str(list(delete_map.keys())))
        logger.info("Delete process completed successfully.")
        sys.exit(0)
    except Exception as e:
        cache = CacheManager(args)
        cache.update_report("delete", "failed", comment=str(e))
        logger.error(f"An error occurred during the delete process: {str(e)}")
        sys.exit(1)

def generate_delete_map(args: Namespace, cache: CacheManager) -> dict[str, DeleteMapNode]:
    """Generate a map of nodes to be deleted based on the cache and reference graph."""
    reference_graph = DbtGraph(args, is_reference=True)

    if getattr(args, "dry_run", False):
        logger.info("Dry run mode enabled - no actual deletions will be performed.")

    # Look for cache
    prev_cache = cache.get_cache()
    if prev_cache is None:
        # Nothing was compared, so passing here would hide a skipped or failed init.
        raise RuntimeError("No cache found, please run 'dbt-ci init' first to generate the necessary manifest files and cache for comparison.")
    logger.info("Cache successfully found - using cached state for comparison")

    deleted_nodes = get_node_ids_from_structured_nodes(prev_cache.get("deleted_nodes", None)) or []
    if len(deleted_nodes) == 0:
        logger.info("No deleted nodes found in cache, skipping...")
        return {}

    logger.info("\n------------------------------------------------------")
    click.secho("State Change Summary:", fg="green", bold=True)
    logger.info(f"\nFound {len(deleted_nodes)} deleted node(s):")
    for node in deleted_nodes:
        node_data = get_node(reference_graph.to_dict(), node)
        logger.info(f"  • {node_data['name'] if node_data else node} [Deleted]")
    logger.info("------------------------------------------------------\n")

    delete_map: dict[str, DeleteMapNode] = {}
    nodes = get_nodes(reference_graph.to_dict(), deleted_nodes)
    if nodes is None or len(nodes) == 0:
        logger.info("No deleted nodes found in manifest, skipping...")
        sys.exit(0)

    if cache.get_cache("target_manifest.json") is None:
        raise RuntimeError("No target manifest found in cache, so deleted nodes cannot be verified against the current project. Run 'dbt-ci init' first.")
    target_graph = DbtGraph(args).to_dict()
    target_table_ids = get_target_table_ids(target_graph)

    for node_id, node_data in nodes.items():
        if node_data["resource_type"] not in ("model", "snapshot"):
            continue

        table_id = get_table_id(node_data)
        if table_id is None:
            logger.warning(f"Missing database, schema or name for node {node_id}. Skipping deletion for this node.")
            continue

        # A moved or renamed file shows up in git as delete + add, but the node itself
        # keeps its unique_id and relation. Dropping it would destroy a live table.
        if get_node(target_graph, node_id) is not None:
            logger.warning(f"Node {node_id} still exists in the target manifest (e.g. its file was moved). Skipping deletion of {table_id}.")
            continue
        if table_id in target_table_ids:
            logger.warning(f"Relation {table_id} is still used by a node in the target manifest. Skipping deletion for {node_id}.")
            continue

        delete_map[node_id] = {
            "type": node_data["resource_type"],
            "name": node_data["name"],
            "table_id": table_id
        }

    return delete_map


def get_table_id(node_data: DependencyGraphNode) -> str | None:
    """Return the `database.schema.alias` relation of a node, or None if any part is missing."""
    database = node_data.get("database", None)
    schema = node_data.get("schema", None)
    name = get_relation_name(node_data)
    if any(x is None for x in (database, schema, name)):
        return None
    return f"{database}.{schema}.{name}"


def get_target_table_ids(target_graph: DependencyGraph) -> set[str]:
    """Collect the relations of every model and snapshot that still exists in the target manifest."""
    table_ids: set[str] = set()
    for node_type in ("model", "snapshot"):
        for node_data in (target_graph.get(node_type) or {}).values():
            table_id = get_table_id(node_data)
            if table_id is not None:
                table_ids.add(table_id)
    return table_ids
