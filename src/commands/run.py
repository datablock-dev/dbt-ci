"""
Run command for dbt-ci
"""

import sys
from argparse import Namespace
from itertools import chain
from typing import Dict, List
import click
from src.dependency_graph import DbtGraph
from src.parser import get_downstream_dependencies, get_node_ids_from_structured_nodes
from src.schema import RunModes, RunnerConfig
from src.variables import Variables
from src.variables.config import MODE_MAPPING, NODE_TYPE_COMMAND_MAPPING
from src.cache import CacheManager
from src.runners import run_dbt_command, append_dbt_variables_to_command

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
        target_graph = DbtGraph(variables)
        reference_graph = DbtGraph(variables, user_production_state=True)
        
        # Look for cache
        prev_cache = cache.get_cache()
        if prev_cache is None: # Should we exit here instead of compiling?
            click.echo("No cache found, please run 'dbt-ci init' first to generate the necessary manifest files and cache for comparison.")
            return

            click.echo("No cache found, compiling DBT")
            run_dbt_command(
                command_args=append_dbt_variables_to_command(["compile"], variables),
                runner_config=RunnerConfig(variables.__dict__),
                quiet=False
            )
        else:
            click.echo("Cache successfully found - using cached state for comparison")

        modified_nodes_dict = {
            "modified_nodes": get_node_ids_from_structured_nodes(cache.get_cache().get("modified_nodes", None)) or [],
            "deleted_nodes": get_node_ids_from_structured_nodes(cache.get_cache().get("deleted_nodes", None)) or []
        }

        modified_nodes = list(
            chain(
                modified_nodes_dict["modified_nodes"],
                modified_nodes_dict["deleted_nodes"],
            )
        )

        if len(modified_nodes) == 0:
            click.echo("No modified or deleted nodes found in cache, skipping...")
            return
        
        click.echo(f"\nFound {len(modified_nodes)} modified model(s):")
        for node in modified_nodes:
            string = f"  • {node.split('.')[-1]}"
            if node in modified_nodes_dict["deleted_nodes"]:
                string += " [Deleted]"
            elif node in modified_nodes_dict["modified_nodes"]:
                string += " [Modified]"
            
            click.echo(string)

        run_with_mode(
            mode=variables.nodes,
            variables=variables,
            target_graph=target_graph,
            modified_nodes_dict=modified_nodes_dict,
            modified_nodes=modified_nodes
        )
        return
        
        # Build dbt run command with selector
        result = run_dbt_command(
            command_args=append_dbt_variables_to_command(["run", "--select", " ".join(downstream_dependencies)], variables),
            runner_config=RunnerConfig(variables.__dict__),
            quiet=False
        )
        
        if result and result.returncode == 0:
            click.echo(f"\n✅ Successfully ran {len(downstream_dependencies)} model(s)")
        else:
            click.echo("\n❌ Run failed", err=True)
            sys.exit(1)
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)

def run_with_mode(
    mode: RunModes,
    variables: Namespace,
    target_graph: DbtGraph,
    modified_nodes_dict: Dict[str, List[str]],
    modified_nodes: List[str]
):
    """Run modified nodes with specific dbt command based on mode"""
    runner_config = RunnerConfig(variables.__dict__)
    run_order = ["seed", "run", "test", "snapshot"]
    if mode != "all":
        run_order = [MODE_MAPPING[mode]]

    for command in run_order:
        click.echo(f"\nIdentifying modified nodes of type: {mode}")
        downstream_dependencies = get_downstream_dependencies(
            dependency_graph=target_graph.to_dict(),
            node_ids=modified_nodes,
            node_type=NODE_TYPE_COMMAND_MAPPING[mode]
        )

        downstream_dependencies = get_downstream_dependencies(
            dependency_graph=target_graph.to_dict(),
            node_ids=modified_nodes,
            node_type=NODE_TYPE_COMMAND_MAPPING[mode]
        )

        if downstream_dependencies is None:
            click.echo("No downstream dependencies found for modified nodes, skipping...")
            return

        click.echo("\nThe following models will be run due to changes, including downstream dependencies:")
        if len(modified_nodes_dict["modified_nodes"]) > 0:
            for node in modified_nodes_dict["modified_nodes"]:
                click.echo(f"  • [Modified] {node}")
        
        for node in downstream_dependencies:
            click.echo(f"  • [Downstream dependency] {node}")

        click.echo(f"\n🚀 Running modified {mode}...")

        result = run_dbt_command(
            command_args=append_dbt_variables_to_command([command, "--select", " ".join(downstream_dependencies)], variables),
            runner_config=runner_config,
            quiet=False
        )

        if result and result.returncode == 0:
            click.echo(f"\n✅ Successfully ran {len(downstream_dependencies)} model(s)")
        else:
            click.echo("\n❌ Run failed", err=True)
            sys.exit(1)

    return
