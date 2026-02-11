"""
    Delete command for dbt-ci
"""

import sys
from typing import Dict
import click
import logging
from argparse import Namespace
from src.cache import CacheManager
from src.dependency_graph import DbtGraph
from src.schema import DeleteMapNode
from src.utilities.getters import get_node_ids_from_structured_nodes, get_nodes
from src.variables import Variables

logger = logging.getLogger(__name__)

def delete(**kwargs):
    """Delete deleted dbt models"""
    click.secho("DBT CI Delete", fg="green", bold=True)
    args = Namespace(**kwargs)
    cache = CacheManager()
    config = Variables(args)
    variables = config.to_namespace()
    target_graph = DbtGraph(variables)
    reference_graph = DbtGraph(variables, user_production_state=True)
    
    if variables.dry_run:
        click.echo("Dry run mode enabled - no actual deletions will be performed.")

    # Look for cache
    prev_cache = cache.get_cache()
    if prev_cache is None: # Should we exit here instead of compiling?
        click.echo("No cache found, please run 'dbt-ci init' first to generate the necessary manifest files and cache for comparison.")
        return
    click.echo("Cache successfully found - using cached state for comparison")

    deleted_nodes = get_node_ids_from_structured_nodes(cache.get_cache().get("deleted_nodes", None)) or []
    if len(deleted_nodes) == 0:
        click.echo("No deleted nodes found in cache, skipping...")
        return

    click.echo("\n------------------------------------------------------")
    click.secho("State Change Summary:", fg="green", bold=True)
    click.echo(f"\nFound {len(deleted_nodes)} deleted node(s):")
    for node in deleted_nodes:
        click.echo(f"  • {node.split('.')[-1]} [Deleted]")
    click.echo("------------------------------------------------------\n")

    delete_map: Dict[str, DeleteMapNode] = {}
    nodes = get_nodes(reference_graph.to_dict(), deleted_nodes)
    if nodes is None or len(nodes) == 0:
        logger.info("No deleted nodes found in manifest, skipping...")
        sys.exit(0)
    
    for node_id, node_data in nodes.items():
        if node_data["resource_type"] not in ("model", "snapshot"):
            continue

        database = node_data.get("database", None)
        schema = node_data.get("schema", None)
        name = node_data.get("config", {}).get('alias', None) or node_data.get("name", None)
        table_id = f"{database}.{schema}.{name}"

        if any(x is None for x in (database, schema, name)):
            logger.warning(f"Missing database, schema or name for node {node_id}. Skipping deletion for this node.")
            continue
            
        delete_map[node_id] = {
            "type": node_data["resource_type"],
            "name": node_data["name"],
            "table_id": table_id
        }

    click.echo("\n------------------------------------------------------")
    click.secho(f"Nodes to be deleted ({len(delete_map)})", fg="green", bold=True)
    for node in delete_map.values():
        click.echo(f"  • {node['table_id']}")
    click.echo("------------------------------------------------------\n")

    if variables.dry_run:
        click.echo("\nDry run complete - no nodes were actually deleted.")
    
    click.echo("There is currently no automated way to delete models from the data warehouse, please manually review the deleted nodes above and remove them from your warehouse as needed.")
    return