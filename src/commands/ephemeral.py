"""
Ephemeral command for dbt-ci
"""

import sys
from argparse import Namespace
import click
from src.cache import CacheManager
from src.dependency_graph import DbtGraph
from src.variables import Variables


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

        # Look for cache
        prev_cache = cache.get_cache()
        if prev_cache is None: # Should we exit here instead of compiling?
            click.echo("No cache found, please run 'dbt-ci init' first to generate the necessary manifest files and cache for comparison.")
            return
        
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)

"""
    Models: By default, select all downstream dependencies (full graph)
    Tests: By default, select upstream depedendenceis (1 level)
    Snapshots: By default, only select upstream dependencies (1 level)
"""