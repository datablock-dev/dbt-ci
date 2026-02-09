"""
    Delete command for dbt-ci
"""

from argparse import Namespace
import click
from src.cache import CacheManager
from src.dependency_graph import DbtGraph
from src.utilities.getters import get_node_ids_from_structured_nodes, get_nodes
from src.variables import Variables


def delete(**kwargs):
    """Delete deleted dbt models"""
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

    modified_nodes = get_node_ids_from_structured_nodes(cache.get_cache().get("deleted_nodes", None)) or []
    if len(modified_nodes) == 0:
        click.echo("No deleted nodes found in cache, skipping...")
        return

    click.echo(f"\nFound {len(modified_nodes)} deleted nodes(s):")
    for node in modified_nodes:
        click.echo(f"  • {node} [Deleted]")

    if variables.dry_run:
        click.echo("\nDry run complete - no nodes were actually deleted.")
    
    click.echo("There is currently no automated way to delete models from the data warehouse, please manually review the deleted nodes above and remove them from your warehouse as needed.")
    return