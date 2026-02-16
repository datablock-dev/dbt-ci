"""Run command for dbt-ci"""

import sys
import logging
from argparse import Namespace
from itertools import chain
from typing import Dict, List
import click
from src.dependency_graph import DbtGraph
from src.schema import RunModes, RunnerConfig
from src.variables import Variables
from src.variables.config import MODE_MAPPING, NODE_TYPE_COMMAND_MAPPING, REVERSE_MODE_MAPPING
from src.cache import CacheManager
from src.logging import print_exception
from src.runners import run_dbt_command, append_dbt_variables_to_command
from src.utilities.graph_utils import (
    filter_node_ids_by_type,
    get_downstream_dependencies,
    get_node_ids_from_structured_nodes
)

logger = logging.getLogger(__name__)

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
        click.secho("DBT CI Run", fg="green", bold=True)
        args = Namespace(**kwargs)
        cache = CacheManager()
        config = Variables(args, command='run')
        variables = config.to_namespace()
        cache.start_report("run", variables)
        target_graph = DbtGraph(variables)
                
        # Look for cache
        prev_cache = cache.get_cache()
        if prev_cache is None: # Should we exit here instead of compiling?
            logger.error("No cache found, please run 'dbt-ci init' first to generate the necessary manifest files and cache for comparison.")
            return
        logger.info("Cache successfully found - using cached state for comparison")

        modified_nodes_dict = {
            "modified_nodes": get_node_ids_from_structured_nodes(cache.get_cache().get("modified_nodes", None)) or [],
            "new_nodes": get_node_ids_from_structured_nodes(cache.get_cache().get("new_nodes", None)) or [],
            "deleted_nodes": get_node_ids_from_structured_nodes(cache.get_cache().get("deleted_nodes", None)) or []
        }
        modified_nodes = [value for values in modified_nodes_dict.values() for value in values]

        if len(modified_nodes) == 0:
            logger.info("No modified, new, or deleted nodes found in cache, skipping...")
            sys.exit(0)
        
        logger.info("\n-------------------------------------------------------")
        logger.info(f"Found {len(modified_nodes)} modified model(s):")
        for node in modified_nodes:
            string = f"  • {node.split('.')[-1]}"
            if node in modified_nodes_dict["deleted_nodes"]:
                string += " [Deleted]"
            elif node in modified_nodes_dict["modified_nodes"]:
                string += " [Modified]"
            elif node in modified_nodes_dict["new_nodes"]:
                string += " [New]"
            
            logger.info(string)
        logger.info("-------------------------------------------------------\n")

        run_with_mode(
            mode=variables.nodes,
            variables=variables,
            target_graph=target_graph,
            modified_nodes_dict=modified_nodes_dict,
            modified_nodes=modified_nodes
        )

        cache.update_report("run", "completed")
        logger.info("\nAll done!")
    except Exception as e:
        cache.update_report("run", "failed", comment=str(e))
        print_exception(e)
        sys.exit(1)

def run_with_mode(
    mode: RunModes,
    variables: Namespace,
    target_graph: DbtGraph,
    modified_nodes_dict: Dict[str, List[str]],
    modified_nodes: List[str]
):
    """Run modified nodes with specific dbt command based on mode"""
    try:
        runner_config = RunnerConfig(variables.__dict__)
        run_order = ["seed", "run", "test", "snapshot"]
        if mode != "all":
            run_order = [MODE_MAPPING[mode]]

        for command in run_order:
            logger.info(f"\nIdentifying modified nodes of type: {REVERSE_MODE_MAPPING[command]}")
            node_type = NODE_TYPE_COMMAND_MAPPING[REVERSE_MODE_MAPPING[command]]

            # Get downstream dependencies for this node type
            set_of_downstream_dependencies = get_downstream_dependencies(
                dependency_graph=target_graph.to_dict(),
                node_ids=modified_nodes,  # All modified, new, deleted
                node_type=node_type
            )
            # Convert to list (function returns set or None)
            downstream_dependencies = list(set_of_downstream_dependencies) if set_of_downstream_dependencies else []

            # Combine all nodes that need to run (modified + new + downstream)
            nodes_to_run = filter_node_ids_by_type(
                dependency_graph=target_graph.to_dict(),
                node_type=node_type,
                node_ids=list(set(
                    modified_nodes_dict.get("modified_nodes", []) +
                    modified_nodes_dict.get("new_nodes", []) +
                    downstream_dependencies
                ))
            )

            if len(nodes_to_run) == 0:
                logger.info(f"No {REVERSE_MODE_MAPPING[command]} to run")
                continue

            modified_of_type = [n for n in modified_nodes_dict.get("modified_nodes", []) if n in nodes_to_run]

            # Display what will run, categorized by change type
            logger.info("\n-------------------------------------------------------")
            logger.info(f"The following {REVERSE_MODE_MAPPING[command]} will be run:")
            for node in modified_of_type:
                logger.info(f"  • [Modified] {node}")

            new_of_type = [n for n in modified_nodes_dict.get("new_nodes", []) if n in nodes_to_run]
            for node in new_of_type:
                logger.info(f"  • [New] {node}")

            downstream_of_type = [n for n in downstream_dependencies if n in nodes_to_run]
            for node in downstream_of_type:
                logger.info(f"  • [Downstream] {node}")
            logger.info(f"\nTotal {REVERSE_MODE_MAPPING[command]} to run: {len(nodes_to_run)}")
            logger.info("-------------------------------------------------------\n")

            logger.info(f"\n[{REVERSE_MODE_MAPPING[command].upper()}] - Running nodes...")

            if runner_config.get("dry_run", False):
                logger.info("DRY RUN: Command would be executed")
                continue

            result = run_dbt_command(
                command_args=append_dbt_variables_to_command([command, "--select", " ".join(nodes_to_run)], variables),
                runner_config=runner_config
            )

            if result and result.returncode == 0:
                logger.info(f"\n✅ Successfully ran {len(nodes_to_run)} {REVERSE_MODE_MAPPING[command]}(s)")
            else:
                logger.error("\n❌ Run failed")
                sys.exit(1)
    except Exception as e:
        print_exception(e)
        sys.exit(1)
