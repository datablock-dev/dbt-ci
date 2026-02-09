"""Ephemeral command for dbt-ci"""

from itertools import chain
import sys
from argparse import Namespace
import click
from src.cache import CacheManager
from src.dependency_graph import DbtGraph
from src.parser import get_downstream_dependencies, get_node_ids_from_structured_nodes
from src.variables import Variables

CONNECTORS = {
    "bigquery": None
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

        modified_nodes = list(
            chain(
                prev_cache.get("modified_nodes", []),
                prev_cache.get("deleted_nodes", []),
                #prev_cache.get("new_nodes", []) --> In ephemeral mode we ignore new nodes
            )
        )

        if len(modified_nodes) == 0:
            click.echo("No modified or deleted nodes found in cache, skipping...")
            return


                
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)

"""
    Models: By default, select all downstream dependencies (full graph)
    Tests: By default, select upstream depedendenceis (1 level)
    Snapshots: By default, only select upstream dependencies (1 level)
"""
