"""Migration command for dbt CI."""

import sys
import logging
from argparse import Namespace
from typing import Any, cast
import click
from dbt_ci.errors import DbtCiError
from dbt_ci.utilities.cache import CacheManager
from dbt_ci.dbt.flags import apply_cached_config
from dbt_ci.graph.dependency_graph import DbtGraph
from dbt_ci.utilities.logging import print_exception, redact_namespace
from dbt_ci.schema import MigrationMap, SupportedConnectors
from dbt_ci.connectors import get_connector
from dbt_ci.utilities.paths import get_profile
from dbt_ci.graph.graph_utils import (
    filter_node_ids_by_type,
    get_node_ids_from_structured_nodes,
    get_nodes,
    get_relation_name,
)

logger = logging.getLogger(__name__)


def migration(args: Namespace):
    """
    Rebuild the incremental models whose partitioning configuration changed.

    The change set comes from the cache `init` wrote. Each affected table is copied into
    a new table with the new partitioning (keeping its clustering and partition options),
    then swapped into place, which only the native BigQuery connector supports.
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
            logger.error(
                f"Connector '{connector_type}' does not support migration strategy, which is "
                "required for migration command."
            )
            sys.exit(1)

        # Setup migraiton connector
        migration_connector = connector.get("strategies").get("migration", None)
        if migration_connector is None:
            logger.error(
                f"Connector '{connector_type}' does not have a migration strategy implemented, "
                "which is required for migration command."
            )
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
        cache.update_report(
            "migrate", "completed", comment=str(list(migration_map["nodes"].keys()))
        )
        logger.info("Migration completed successfully.")
    except Exception as e:
        cache = CacheManager(args)
        cache.update_report("migrate", "failed", comment=str(e))
        print_exception(e, "Migration failed")
        sys.exit(1)


def generate_migration_map(
    args: Namespace,
    cache: CacheManager,
) -> MigrationMap:
    """Map the modified incremental models whose partitioning differs from the reference."""
    target_graph = DbtGraph(args)
    reference_graph = DbtGraph(args, is_reference=True)

    # Look for cache
    prev_cache = cache.get_cache()
    if prev_cache is None:
        raise DbtCiError(
            "No cache found, please run 'dbt-ci init' first to generate the necessary "
            "manifest files and cache for comparison."
        )
    logger.info("Cache successfully found - using cached state for comparison")

    modified_nodes_dict = {
        "modified_nodes": get_node_ids_from_structured_nodes(prev_cache.get("modified_nodes"))
        or [],
    }

    selected_nodes = filter_node_ids_by_type(
        dependency_graph=target_graph.to_dict(),
        node_ids=modified_nodes_dict["modified_nodes"],
        node_type=["model"],
    )
    migration_map: MigrationMap = {"connector": get_profile(args)["type"], "nodes": {}}
    if len(selected_nodes) == 0:
        logger.info("No modified models found in cache, skipping...")
        return migration_map

    target_nodes = get_nodes(target_graph.to_dict(), selected_nodes) or {}
    reference_nodes = get_nodes(reference_graph.to_dict(), selected_nodes) or {}

    for node_id, node_metadata in target_nodes.items():
        node_config = cast(dict[str, Any], node_metadata.get("config") or {})
        reference_node = reference_nodes.get(node_id)
        reference_config = cast(dict[str, Any], reference_node["config"] if reference_node else {})
        target_partitioning_config = node_config.get("partition_by", None)
        reference_partitioning_config = reference_config.get("partition_by", None)
        # Only incremental models keep their table between runs, so only they need migrating
        if node_config.get("materialized", None) != "incremental":
            continue

        # Check if partitioning has been changed
        # Dict comparison is order-insensitive since Python 3.7+
        if target_partitioning_config != reference_partitioning_config:
            migration_map["nodes"][node_id] = {
                "table_id": ".".join(
                    [
                        node_metadata.get("database") or "",
                        node_metadata.get("schema") or "",
                        get_relation_name(node_metadata) or "",
                    ]
                ),
                "cluster_by": node_config.get("cluster_by", None),
                "require_partition_filter": node_config.get("require_partition_filter", None),
                "partition_expiration_days": node_config.get("partition_expiration_days", None),
                "compiled_code": node_metadata.get("compiled_code", None),
                "old_partitioning": reference_partitioning_config,
                "new_partitioning": target_partitioning_config,
            }

    return migration_map
