"""
    Ephemeral command for dbt-ci

    Models: By default, select all downstream dependencies (full graph)
    Tests: By default, select upstream depedendenceis (1 level)
    Snapshots: By default, only select upstream dependencies (1 level)
"""

import sys
from itertools import chain
from argparse import Namespace
from typing import Dict, Optional
import click
from src.cache import CacheManager
from src.connectors.bigquery import bigquery_ephemeral_strategy
from src.dependency_graph import DbtGraph
from src.schema import EphemeralConnectors, EphemeralMapNode
from src.variables import Variables
from src.utilities.getters import (
    get_downstream_dependencies,
    get_node_ids_from_structured_nodes,
    get_nodes,
    get_upstream_dependencies
)

CONNECTORS: EphemeralConnectors = {
    "bigquery": bigquery_ephemeral_strategy
}

def ephemeral(**kwargs):
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
        args = Namespace(**kwargs)
        cache = CacheManager()
        config = Variables(args)
        variables = config.to_namespace()
        target_graph = DbtGraph(variables)
        reference_graph = DbtGraph(variables, user_production_state=True)
        connector_type = variables.target_config.get("type")
        ephemeral_connector = CONNECTORS.get(connector_type, None)

        if connector_type is None:
            click.echo(f"Missing connector type for ephemeral mode: {connector_type}. Supported connectors: {list(CONNECTORS.keys())}")
        elif CONNECTORS.get(connector_type) is None:
            click.echo(f"Unsupported connector type for ephemeral mode: {connector_type}. Supported connectors: {list(CONNECTORS.keys())}")
            return

        # Look for cache
        prev_cache = cache.get_cache()
        if prev_cache is None: # Should we exit here instead of compiling?
            click.echo("No cache found, please run 'dbt-ci init' first to generate the necessary manifest files and cache for comparison.")
            return
        click.echo("Cache successfully found - using cached state for comparison")

        modified_nodes_dict = {
            "modified_nodes": get_node_ids_from_structured_nodes(cache.get_cache().get("modified_nodes", None)) or [],
            "deleted_nodes": get_node_ids_from_structured_nodes(cache.get_cache().get("deleted_nodes", None)) or []
        }

        modified_nodes = list(chain(
            modified_nodes_dict["modified_nodes"],
            modified_nodes_dict["deleted_nodes"],
        ))

        if len(modified_nodes) == 0:
            click.echo("No modified or deleted nodes found in cache, skipping...")
            return

        # Deleted nodes dont need to be tested.
        # However, we need to include the modified nodes & their downstream
        # dependencies to truly test that the change does not break anything.
        # We skip newly created nodes as they should not be included in ephemeral checks
        # They should be created in the PR/merge
        selected_nodes = list(chain(
            modified_nodes_dict["modified_nodes"] or [],
            get_downstream_dependencies(target_graph.to_dict(), modified_nodes, "model") or [],
            get_upstream_dependencies(target_graph.to_dict(), modified_nodes, "snapshot") or [],
            get_upstream_dependencies(target_graph.to_dict(), modified_nodes, "test") or []
        ))

        # Lets get all metadata related to these downstream dependencies
        #print(downstream_dependencies)
        target_nodes = get_nodes(target_graph.to_dict(), selected_nodes)
        reference_nodes = get_nodes(reference_graph.to_dict(), selected_nodes)

        # Now we build a dict of target & reference nodes for the engine
        # to decide how to execute and create the ephemeral environment
        ephemeral_map: Dict[str, EphemeralMapNode] = {}

        # We use reference since it will also include deleted nodes
        # In target, they wont exist and return None
        for node_id, node_metadata in reference_nodes.items():
            # Skip ephemeral models since they are not materialized and should not be executed
            if node_metadata["materialized"] in ("ephemeral", "view", "table"):
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

        # Pass the ephemeral map and variables to the connector strategy which
        # will handle the ephemeral execution logic based on the connector type
        ephemeral_connector(ephemeral_map, variables)
        click.echo("Ephemeral strategy completed successfully.")
        click.echo("Now you can run your dbt command with the appropriate selection to target the ephemeral models and their downstream dependencies.")
        sys.exit(0)
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)

def full_config_or_none(
    database: Optional[str],
    schema: Optional[str],
    name: Optional[str],
    alias: Optional[str] = None
) -> Dict[str, Optional[str]] | None:
    """Helper function to return full config dict if all values are present, otherwise None."""
    if any(v is None for v in (database, schema, name)):
        return None
    return {
        "database": database,
        "schema": schema,
        "name": name,
        "alias": alias,
    }