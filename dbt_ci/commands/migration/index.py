"""Migration command for dbt CI."""
import sys
import logging
from argparse import Namespace
from typing import cast
import click
from dbt_ci.utilities.cache import CacheManager
from dbt_ci.dbt.flags import apply_cached_config
from dbt_ci.graph.dependency_graph import DbtGraph
from dbt_ci.utilities.logging import print_exception, redact_namespace
from dbt_ci.schema import (
    DEFAULT_PHYSICAL_CONFIG_KEYS,
    PHYSICAL_CONFIG_KEYS,
    MigrationMap,
    SupportedConnectors,
)
from dbt_ci.connectors import get_connector
from dbt_ci.utilities.paths import get_profile
from dbt_ci.graph.graph_utils import (
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
        logger.debug(f"Running with the following arguments: {redact_namespace(args)}")
        cache = CacheManager(args)
        cache.start_report("migrate", args)
        apply_cached_config(args)
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
                logger.info(f"  - Old Config: {node_info.get('old_config', node_info['old_partitioning'])}")
                logger.info(f"  - New Config: {node_info.get('new_config', node_info['new_partitioning'])}")
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

    connector_type = get_profile(args)["type"]
    physical_config_keys = get_physical_config_keys(connector_type)

    migration_map: MigrationMap = {
        "connector": connector_type,
        "nodes": {}
    }

    for node_id, node_metadata in target_nodes.items():
        node_config = node_metadata.get("config", {})
        reference_config = reference_nodes.get(node_id, {}).get("config", {})
        target_physical_config = extract_physical_config(node_config, physical_config_keys)
        reference_physical_config = extract_physical_config(reference_config, physical_config_keys)
        # Skip non-incremental models: every other materialization is rebuilt by dbt on each
        # run, so it already picks up a new physical layout without a migration.
        if node_config.get("materialized", None) != "incremental":
            continue

        # Check if the physical layout has been changed
        # Dict comparison is order-insensitive since Python 3.7+
        if target_physical_config != reference_physical_config:
            # 'name' selects the model for dbt (which does not know about aliases), while
            # 'table_id' addresses the relation in the warehouse (which only knows the alias).
            relation_name = node_config.get("alias", None) or node_metadata.get("name", "")
            migration_map["nodes"][node_id] = {
                "name": node_metadata.get("name", ""),
                "materialization": node_config.get("materialized", None),
                "table_id": f"{node_metadata.get('database', '')}.{node_metadata.get('schema', '')}.{relation_name}",
                "compiled_code": node_metadata.get("compiled_code", None),
                "old_partitioning": reference_config.get("partition_by", None),
                "new_partitioning": node_config.get("partition_by", None),
                "old_config": reference_physical_config,
                "new_config": target_physical_config
            }

    return migration_map

def get_physical_config_keys(connector_type: str) -> tuple[str, ...]:
    """Return the model config keys that determine a relation's physical layout for an adapter."""
    return PHYSICAL_CONFIG_KEYS.get(connector_type, DEFAULT_PHYSICAL_CONFIG_KEYS)

def extract_physical_config(node_config: dict, keys: tuple[str, ...]) -> dict:
    """Pick the physical-layout entries out of a node's config, dropping unset ones."""
    return {key: node_config[key] for key in keys if node_config.get(key) is not None}