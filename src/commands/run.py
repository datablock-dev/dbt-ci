"""Run command for dbt-ci"""

import sys
from argparse import Namespace
from itertools import chain
from typing import Dict, List
import click
from src.dependency_graph import DbtGraph
from src.schema import RunModes, RunnerConfig
from src.variables import Variables
from src.variables.config import MODE_MAPPING, NODE_TYPE_COMMAND_MAPPING, REVERSE_MODE_MAPPING
from src.cache import CacheManager
from src.runners import run_dbt_command, append_dbt_variables_to_command
from src.utilities.getters import (
    filter_node_ids_by_type,
    get_downstream_dependencies,
    get_node_ids_from_structured_nodes
)

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
        click.echo("\nAll done!")
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
        click.echo(f"\nIdentifying modified nodes of type: {REVERSE_MODE_MAPPING[command]}")
        node_type = NODE_TYPE_COMMAND_MAPPING[REVERSE_MODE_MAPPING[command]]
        downstream_dependencies = get_downstream_dependencies(
            dependency_graph=target_graph.to_dict(),
            node_ids=modified_nodes,
            node_type=node_type
        )

        if downstream_dependencies is None:
            downstream_dependencies = []
            click.echo("No downstream dependencies found for modified nodes")

        # Filter modified nodes by current node type
        modified_nodes_of_type = filter_node_ids_by_type(
            dependency_graph=target_graph.to_dict(),
            node_ids=modified_nodes_dict["modified_nodes"],
            node_type=node_type
        )
        
        final_nodes_to_run = filter_node_ids_by_type(
            dependency_graph=target_graph.to_dict(),
            node_ids=list(set(modified_nodes_dict["modified_nodes"]).union(set(downstream_dependencies))),
            node_type=node_type
        )

        if len(final_nodes_to_run) == 0:
            click.echo(f"No {REVERSE_MODE_MAPPING[command]} to run")
            continue

        click.echo(f"\nThe following {REVERSE_MODE_MAPPING[command]} will be run due to changes, including downstream dependencies:")
        if len(modified_nodes_of_type) > 0:
            for node in modified_nodes_of_type:
                click.echo(f"  • [Modified] {node}")
        
        # Only show downstream dependencies that are actually in final_nodes_to_run
        downstream_nodes_of_type = [node for node in downstream_dependencies if node in final_nodes_to_run]
        for node in downstream_nodes_of_type:
            click.echo(f"  • [Downstream dependency] {node}")

        click.echo(f"\n[{REVERSE_MODE_MAPPING[command].upper()}] - Running modified nodes...")

        result = run_dbt_command(
            command_args=append_dbt_variables_to_command([command, "--select", " ".join(final_nodes_to_run)], variables),
            runner_config=runner_config,
            quiet=False
        )

        if result and result.returncode == 0:
            click.echo(f"\n✅ Successfully ran {len(final_nodes_to_run)} {REVERSE_MODE_MAPPING[command]}(s)")
        else:
            click.echo("\n❌ Run failed", err=True)
            sys.exit(1)

    return
