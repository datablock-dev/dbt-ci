"""Migration command for dbt CI."""
import sys
import logging
from argparse import Namespace
from typing import cast
import click
from src.cache import CacheManager
from src.graph.dependency_graph import DbtGraph
from src.logging import print_exception
from src.schema import MigrationMap, SupportedConnectors
from src.connectors import get_connector
from src.utilities.paths import get_profile
from src.graph.graph_utils import (
    filter_node_ids_by_multiple_types,
    get_node_ids_from_structured_nodes,
    get_nodes
)

logger = logging.getLogger(__name__)

def migration(args: Namespace):
    """
    Perform a migration operation.

    This function serves as a placeholder for the migration command.
    It currently does not implement any functionality.

    Args:
        args: Namespace object containing command-line arguments.
    """
    try:
        click.secho("DBT CI Migration", fg="green", bold=True)
        logger.debug(f"Running with the following arguments: {args}")
        cache = CacheManager(args)
        cache.start_report("migrate", args)
        connector_type = cast(SupportedConnectors, get_profile(args)["type"])
        connector = get_connector(connector_type)

        if connector is None:
            logger.error(f"Connector '{connector_type}' does not support migration strategy, which is required for migration command.")
            sys.exit(1)

        # Setup migraiton connector
        migration_connector = connector.get("strategies").get("migration", None)
        if migration_connector is None:
            logger.error(f"Connector '{connector_type}' does not have a migration strategy implemented, which is required for migration command.")
            sys.exit(1)

        # Determine if there has been a change in clustering or partitioning configuration
        migration_map = generate_migration_map(args, cache)

        if len(migration_map["nodes"]) == 0:
            logger.info("No partitioning changes detected between target and reference graphs.")
            sys.exit(0)
        else:
            logger.info(f"Detected {len(migration_map['nodes'])} models with partitioning changes.")
            logger.info("\n------------------------------------------------------")
            for node_id, node_info in migration_map["nodes"].items():
                logger.info(f"Model: {node_id}")
                logger.info(f"  - Table ID: {node_info['table_id']}")
                logger.info(f"  - Old Partitioning: {node_info['old_partitioning']}")
                logger.info(f"  - New Partitioning: {node_info['new_partitioning']}")
            logger.info("------------------------------------------------------\n")

        if getattr(args, "dry_run", False):
            logger.info("Dry run mode enabled - no changes will be applied.")
            sys.exit(0)
        
        # Apply partitioning changes
        migration_connector(migration_map, args)
        cache.update_report("migrate", "completed", comment=str(list(migration_map["nodes"].keys())))
        logger.info("Migration completed successfully.")
    except Exception as e:
        cache = CacheManager(args)
        cache.update_report("migrate", "failed", comment=str(e))
        print_exception(e)
        sys.exit(1)

def generate_migration_map(
    args: Namespace,
    cache: CacheManager,
) -> MigrationMap:
    """Compare partitioning configurations between target and reference nodes and return a migration map."""
    target_graph = DbtGraph(args)
    reference_graph = DbtGraph(args, is_reference=True)

    # Look for cache
    prev_cache = cache.get_cache()
    if prev_cache is None: # Should we exit here instead of compiling?
        logger.error("No cache found, please run 'model-lineage init' first to generate the necessary manifest files and cache for comparison.")
        sys.exit(1)
    logger.info("Cache successfully found - using cached state for comparison")

    modified_nodes_dict = {
        "modified_nodes": get_node_ids_from_structured_nodes(cache.get_cache().get("modified_nodes", None)) or [],
    }

    selected_nodes = filter_node_ids_by_multiple_types(
        dependency_graph=target_graph.to_dict(), 
        node_ids=modified_nodes_dict["modified_nodes"], 
        node_types=["model"]
    )
    if len(selected_nodes) == 0:
        logger.info("No modified models found in cache, skipping...")
        sys.exit(0)

    target_nodes = get_nodes(target_graph.to_dict(), selected_nodes)
    reference_nodes = get_nodes(reference_graph.to_dict(), selected_nodes)

    migration_map: MigrationMap = {
        "connector": get_profile(args)["type"],
        "nodes": {}
    }

    for node_id, node_metadata in target_nodes.items():
        node_config = node_metadata.get("config", {})
        target_partitioning_config = node_config.get("partition_by", None)
        reference_partitioning_config = reference_nodes.get(node_id, {}).get("config", {}).get("partition_by", None)
        # Skip non-incremental models since partitioning changes only apply to incremental models in BigQuery
        if node_config.get("materialized", None) != "incremental":
            continue
        
        # Check if partitioning has been changed
        # Dict comparison is order-insensitive since Python 3.7+
        if target_partitioning_config != reference_partitioning_config:
            migration_map["nodes"][node_id] = {
                "table_id": f"{node_metadata.get('database', '')}.{node_metadata.get('schema', '')}.{node_metadata.get('name', '')}",
                "compiled_code": node_metadata.get("compiled_code", None),
                "old_partitioning": reference_partitioning_config,
                "new_partitioning": target_partitioning_config
            }

    return migration_map