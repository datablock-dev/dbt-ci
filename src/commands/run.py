"""
Run command for dbt-ci
"""

import sys
from argparse import Namespace
from itertools import chain
import click
from src.dependency_graph import DbtGraph
from src.parser import get_downstream_dependencies, get_downstream_dependencies_from_cache, get_node_ids_from_structured_nodes
from src.schema import RunnerConfig
from src.variables import Variables
from src.cache import CacheManager
from src.runners import run_dbt_command, append_dbt_variables_to_command

MODE_MAPPING = {
    "all": None,
    "seeds": "seed",
    "models": "run",
    "tests": "test",
    "snapshots": "snapshot"
}

def run(**kwargs):
    """Run modified dbt models
    
    Detects models that have changed based on state comparison and runs them.
    
    Examples:
        dbt-ci run --state prod-manifest/ --dbt-project-dir ./dbt
        dbt-ci run --state prod-manifest/ --runner docker
        
        # With environment variables
        export DBT_STATE=./dbt/.dbtstate/
        export DBT_PROJECT_DIR=./dbt
        dbt-ci run
    """
    try:
        # Convert kwargs to Namespace and resolve configuration
        # Variables class handles type conversions (tuples->lists, string->bool, etc.)
        args = Namespace(**kwargs)
        cache = CacheManager()
        config = Variables(args)
        variables = config.to_namespace()
        #MODE = MODE_MAPPING[variables.nodes]
        target_graph = DbtGraph(variables)
        reference_graph = DbtGraph(variables, user_production_state=True)
        
        # Look for cache
        prev_cache = cache.get_cache()
        if prev_cache is None: # Should we exit here instead of compiling?
            click.echo("No cache found, compiling DBT")
            run_dbt_command(
                command_args=append_dbt_variables_to_command(["compile"], variables),
                runner_config=RunnerConfig(variables.__dict__),
                quiet=False
            )
        else:
            click.echo("Cache successfully found - using cached state for comparison")

        modified_nodes = list(chain(
            get_node_ids_from_structured_nodes(cache.get_cache().get("modified_nodes", None)) or [],
            get_node_ids_from_structured_nodes(cache.get_cache().get("deleted_nodes", None)) or []
        ))

        print(modified_nodes)
        print(get_downstream_dependencies_from_cache(cache.get_cache().get("deleted_nodes", None)))

        if len(modified_nodes) == 0:
            click.echo("No modified or deleted nodes found in cache, skipping...")
            return
        
        click.echo(f"Found {len(modified_nodes)} modified model(s):")
        downstream_dependencies = get_downstream_dependencies(target_graph.to_dict(), modified_nodes)

        print(downstream_dependencies)
        for node in downstream_dependencies:
            click.echo(f"  • {node}")
        
        click.echo("\n🚀 Running modified models...")
        
        # Build dbt run command with selector
        result = run_dbt_command(
            command_args=append_dbt_variables_to_command(["run", "--select", " ".join(downstream_dependencies)], variables),
            runner_config=RunnerConfig(variables.__dict__),
            quiet=False
        )

        print(f"Test result: {result.stdout}")
        
        if result and result.returncode == 0:
            click.echo(f"\n✅ Successfully ran {len(downstream_dependencies)} model(s)")
        else:
            click.echo("\n❌ Run failed", err=True)
            sys.exit(1)     
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)
