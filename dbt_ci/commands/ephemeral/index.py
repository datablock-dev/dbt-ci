"""
    Ephemeral command for dbt-ci

    Models: By default, select all downstream dependencies (full graph)
    Tests: By default, select upstream depedendenceis (1 level)
    Snapshots: By default, only select upstream dependencies (1 level)
"""

import sys
import logging
from itertools import chain
from argparse import Namespace
from typing import Optional
import click
from dbt_ci.cache import CacheManager
from dbt_ci.connectors import DB_CONNECTORS
from dbt_ci.graph.dependency_graph import DbtGraph
from dbt_ci.logging import print_exception
from dbt_ci.schema import EphemeralMapNode
from dbt_ci.utilities.dbt_commands import clone_command
from dbt_ci.utilities.paths import get_profile
from dbt_ci.graph.graph_utils import (
    filter_node_ids_by_multiple_types,
    get_downstream_dependencies,
    get_node_ids_from_structured_nodes,
    get_nodes,
    get_upstream_dependencies
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
        logger.debug(f"Running with the following arguments: {args}")
        cache = CacheManager(args)
        cache.start_report("ephemeral", args)
        connector_type = get_profile(args)["type"]
        
        # Validate connector before calling get_connector
        if connector_type is None:
            logger.error(f"Missing connector type for ephemeral mode: {connector_type}. Supported connectors: {list(DB_CONNECTORS.keys())}")
            sys.exit(1)
        elif connector_type not in DB_CONNECTORS:
            logger.error(f"Unsupported connector type for ephemeral mode: {connector_type}. Supported connectors: {list(DB_CONNECTORS.keys())}")
            sys.exit(1)
        
        #ephemeral_connector = get_connector(connector_type).get("strategies", {}).get("ephemeral")
        ephemeral_map = generate_ephemeral_map(args, cache)

        # Pass the ephemeral map and variables to the connector strategy which
        # will handle the ephemeral execution logic based on the connector type
        if getattr(args, "dry_run", False):
            if getattr(args, "quiet", False):
                sys.exit(0)
            
            logger.info("Dry run mode enabled - no actual ephemeral environment will be created.")
            logger.info("\n------------------------------------------------------")
            for node_id, node_info in ephemeral_map.items():
                target_table_id = f"{node_info['ephemeral_config']['database']}.{node_info['ephemeral_config']['schema']}.{node_info['ephemeral_config']['name']}" if node_info['ephemeral_config'] else "N/A"
                reference_table_id = f"{node_info['reference_config']['database']}.{node_info['reference_config']['schema']}.{node_info['reference_config']['name']}" if node_info['reference_config'] else "N/A"

                logger.info(f"Model: {node_id}")
                logger.info(f"  - Ephemeral Target: {target_table_id}")
                logger.info(f"  - Reference Target: {reference_table_id}") 
            logger.info("------------------------------------------------------\n")
            sys.exit(0)
        elif len(ephemeral_map) == 0:
            logger.info("No nodes found to create ephemeral environment for. Exiting...")
            sys.exit(0)

        #ephemeral_connector(ephemeral_map, args)
        clone_command(list(ephemeral_map.keys()), args)
        
        # Store cache (ephemeral map) for use in finalize step
        cache.write_ephemeral(ephemeral_map)
        cache.update_report("ephemeral", "completed", comment=str(list(ephemeral_map.keys())))
        logger.info("Ephemeral strategy completed successfully.")
        logger.info("Now you can run your dbt command with the appropriate selection to target the ephemeral models and their downstream dependencies.")
        sys.exit(0)
    except Exception as e:
        cache = CacheManager(args)
        cache.update_report("ephemeral", "failed", comment=str(e))
        print_exception(e)
        sys.exit(1)

def generate_ephemeral_map(
    args: Namespace, 
    cache: CacheManager
) -> dict[str, EphemeralMapNode]:
    """Generate a map of nodes to be included in the ephemeral environment based on the cache and dependency graph."""
    target_graph = DbtGraph(args)
    reference_graph = DbtGraph(args, is_reference=True)

    # Look for cache
    prev_cache = cache.get_cache()
    if prev_cache is None: # Should we exit here instead of compiling?
        logger.error("No cache found, please run 'dbt-ci init' first to generate the necessary manifest files and cache for comparison.")
        sys.exit(1)
    logger.info("Cache successfully found - using cached state for comparison")

    changed_nodes_dict = {
        "modified_nodes": get_node_ids_from_structured_nodes(cache.get_cache().get("modified_nodes", None)) or [],
        "deleted_nodes": get_node_ids_from_structured_nodes(cache.get_cache().get("deleted_nodes", None)) or [],
        "new_nodes": get_node_ids_from_structured_nodes(cache.get_cache().get("new_nodes", None)) or [],
    }

    changed_nodes = list(set(chain(
        changed_nodes_dict["modified_nodes"],
        changed_nodes_dict["deleted_nodes"],
        changed_nodes_dict["new_nodes"],
    )))

    if len(changed_nodes) == 0:
        logger.info("No modified, deleted, or new nodes found in cache, skipping...")
        sys.exit(0)

    # Ephemeral cloning strategy:
    # 1. All modified nodes (models, snapshots, tests)
    # 2. Downstream dependencies of modified & deleted nodes
    # 3. If a snapshot changed, include its upstream dependencies (first level)
    # 4. If a test changed, include its upstream dependencies (first level)
    # Note: New nodes are skipped - they should be created in the PR/merge, not cloned
        
    # Get modified nodes of type that needs to have upstream dependencies included
    # Snapshots & tests
    nodes_with_upstream_deps = list(set(chain(
        filter_node_ids_by_multiple_types(
            dependency_graph=target_graph.to_dict(),
            node_types=["snapshot", "test"],
            node_ids=list(chain(
                changed_nodes_dict["modified_nodes"],
                changed_nodes_dict["new_nodes"],
            ))
        )
    )))
        
    selected_nodes = filter_node_ids_by_multiple_types(
        dependency_graph=target_graph.to_dict(),
        node_types=["model", "snapshot"],
        node_ids=list(chain(
            # 1. All modified nodes (models, snapshots)
            changed_nodes_dict["modified_nodes"],
            changed_nodes_dict["new_nodes"],
            # 2. Upstream dependencies of modified models (first level, only models)
            get_upstream_dependencies(target_graph.to_dict(), changed_nodes, "model") or [],
            # 3. Get upstream dependencies of modified models downstream dependencies (full graph, all types)
            get_upstream_dependencies(
                dependency_graph=target_graph.to_dict(), 
                node_ids=list(get_downstream_dependencies(target_graph.to_dict(), changed_nodes, None) or []),
            ) or [],
            # 4. Indirect Downstream dependencies of modified & deleted nodes (all types)
            get_downstream_dependencies(target_graph.to_dict(), changed_nodes, None) or [],
            # 5. Upstream dependencies of modified snapshots & tests (first level, any type)
            get_upstream_dependencies(target_graph.to_dict(), nodes_with_upstream_deps, None) or [],
        ))
    )

    # Lets get all metadata related to these downstream dependencies
    #print(downstream_dependencies)
    target_nodes = get_nodes(target_graph.to_dict(), selected_nodes)
    reference_nodes = get_nodes(reference_graph.to_dict(), selected_nodes)

    # Now we build a dict of target & reference nodes for the engine
    # to decide how to execute and create the ephemeral environment
    ephemeral_map: dict[str, EphemeralMapNode] = {}

    # We use reference since it will also include deleted nodes
    # In target, they wont exist and return None
    for node_id, node_metadata in reference_nodes.items():
        # Skip ephemeral models since they are not materialized in the database
        # and therefore cannot be cloned
        if (
            node_metadata["materialized"] in ("ephemeral", "view", "table")
            and node_metadata["resource_type"] == "model"
        ):
            continue
            
        target_node = target_nodes.get(node_id, None)
        if target_node is None:
            continue

        ephemeral_map[node_id] = {
            "name": node_metadata["name"],
            "resource_type": node_metadata["resource_type"],
            "ephemeral_config": full_config_or_none(
                database=target_node.get("database", None),
                schema=target_node.get("schema", None),
                name=target_node.get("name", None),
                alias=target_node.get("alias", None),
            ),
            "reference_config": full_config_or_none(
                database=node_metadata.get("database", None),
                schema=node_metadata.get("schema", None),
                name=node_metadata.get("name", None),
                alias=node_metadata.get("alias", None),
            )
        }

    return ephemeral_map
    
def ephemeral_mapping(
    args: Namespace,
    cache: CacheManager
) -> tuple[]:
    

def full_config_or_none(
    database: Optional[str],
    schema: Optional[str],
    name: Optional[str],
    alias: Optional[str] = None
) -> dict[str, Optional[str]] | None:
    """Helper function to return full config dict if all values are present, otherwise None."""
    if any(v is None for v in (database, schema, name)):
        return None
    return {
        "database": database,
        "schema": schema,
        "name": name,
        "alias": alias,
    }