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
from dbt_ci.commands.migration.layout import (
    SQL_ADAPTERS,
    UnsupportedLayoutChange,
    layout_change,
    plan_statements,
)
from dbt_ci.dbt.operations import run_statements
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
    Move incremental models whose table layout changed onto their new layout.

    The change set comes from the cache `init` wrote. On BigQuery each affected table is
    copied into a new table with the new partitioning and swapped into place. On
    Snowflake, Redshift and Databricks the change is applied with DDL that keeps the
    table's rows (see dbt_ci.commands.migration.layout). Other warehouses have no layout
    config for dbt-ci to apply, so there is nothing to migrate.
    """
    try:
        click.secho("DBT CI Migration", fg="green", bold=True)
        logger.debug(f"Running with the following arguments: {redact_namespace(args)}")
        cache = CacheManager(args)
        cache.start_report("migrate", args)
        apply_cached_config(args)
        connector_type = cast(SupportedConnectors, get_profile(args)["type"])

        migration_map = generate_migration_map(args, cache)
        if len(migration_map["nodes"]) == 0:
            logger.info("No table layout changes detected between target and reference graphs.")
            cache.update_report("migrate", "completed", comment="nothing to migrate")
            sys.exit(0)

        logger.info(f"Detected {len(migration_map['nodes'])} model(s) with layout changes.")
        logger.info("\n------------------------------------------------------")
        for node_id, node_info in migration_map["nodes"].items():
            logger.info(f"Model: {node_id}")
            logger.info(f"  - Table ID: {node_info['table_id']}")
            logger.info(f"  - Old layout: {node_info.get('old_layout')}")
            logger.info(f"  - New layout: {node_info.get('new_layout')}")
        logger.info("------------------------------------------------------\n")

        if connector_type in SQL_ADAPTERS:
            migrate_with_sql(args, connector_type, migration_map)
        else:
            migrate_with_connector(args, connector_type, migration_map)

        cache.update_report(
            "migrate", "completed", comment=str(list(migration_map["nodes"].keys()))
        )
        if not getattr(args, "dry_run", False):
            logger.info("Migration completed successfully.")
    except Exception as e:
        cache = CacheManager(args)
        cache.update_report("migrate", "failed", comment=str(e))
        print_exception(e, "Migration failed")
        sys.exit(1)


def migrate_with_connector(
    args: Namespace, connector_type: SupportedConnectors, migration_map: MigrationMap
) -> None:
    """Apply the migration with the warehouse's native connector (BigQuery)."""
    connector = get_connector(connector_type)
    strategies = cast(dict[str, Any], connector.get("strategies") or {}) if connector else {}
    migration_connector = strategies.get("migration")
    if migration_connector is None:
        raise DbtCiError(
            f"dbt-ci cannot migrate tables on '{connector_type}'. Rebuild the models with "
            f"'dbt run --full-refresh --select {' '.join(model_names(migration_map))}'."
        )
    if getattr(args, "dry_run", False):
        logger.info("Dry run mode enabled - no changes will be applied.")
        return
    migration_connector(migration_map, args)


def migrate_with_sql(args: Namespace, adapter_type: str, migration_map: MigrationMap) -> None:
    """
    Plan the DDL for every model, then run it through dbt run-operation.

    Everything is planned before anything runs, so a change that needs a rebuild stops
    the command before any table was touched.
    """
    plans: dict[str, list[str]] = {}
    unsupported: list[str] = []
    for node_id, node in migration_map["nodes"].items():
        try:
            plans[node_id] = plan_statements(
                adapter_type,
                node.get("relation_name") or node["table_id"],
                node.get("old_layout") or {},
                node.get("new_layout") or {},
                node.get("config"),
            )
        except UnsupportedLayoutChange as e:
            unsupported.append(f"{node_id}: {e}")
    if unsupported:
        raise DbtCiError(
            "These layout changes need the table rebuilt, which would lose rows an "
            "incremental model can't rebuild from its sources. Rebuild them with "
            "'dbt run --full-refresh' if that is safe:\n  " + "\n  ".join(unsupported)
        )

    for node_id, statements in plans.items():
        logger.info(f"{node_id}:")
        for statement in statements:
            logger.info(f"  {statement}")
    if getattr(args, "dry_run", False):
        logger.info("Dry run mode enabled - no changes will be applied.")
        return
    for node_id, statements in plans.items():
        run_statements(args, statements)
        logger.info(f"Migrated {node_id}")


def model_names(migration_map: MigrationMap) -> list[str]:
    """Return the model names in a migration map, for a dbt --select."""
    return [node_id.split(".")[-1] for node_id in migration_map["nodes"]]


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

    adapter_type = get_profile(args)["type"]
    for node_id, node_metadata in target_nodes.items():
        node_config = cast(dict[str, Any], node_metadata.get("config") or {})
        reference_node = reference_nodes.get(node_id)
        # A model new on this branch has no table to migrate yet
        if reference_node is None:
            continue
        reference_config = cast(dict[str, Any], reference_node.get("config") or {})
        target_partitioning_config = node_config.get("partition_by", None)
        reference_partitioning_config = reference_config.get("partition_by", None)
        # Only incremental models keep their table between runs, so only they need migrating
        if node_config.get("materialized", None) != "incremental":
            continue

        # Each warehouse sets the layout with its own config keys
        change = layout_change(adapter_type, node_config, reference_config)
        if change is not None:
            old_layout, new_layout = change
            migration_map["nodes"][node_id] = {
                "relation_name": cast(str | None, node_metadata.get("relation_name")),
                "old_layout": old_layout,
                "new_layout": new_layout,
                "config": node_config,
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
