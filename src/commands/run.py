"""Run command for dbt-ci"""

import sys
import logging
from argparse import Namespace
from itertools import chain
from typing import Dict, List, Set
import click
from src.dependency_graph import DbtGraph
from src.cache import CacheManager
from src.logging import print_exception
from src.runners import run_dbt_command, append_dbt_variables_to_command
from src.schema import (
    DependencyGraph,
    DependencyGraphNodeType,
    RunModes, 
    RunnerConfig, 
    MODE_MAPPING, 
    NODE_TYPE_COMMAND_MAPPING, 
    REVERSE_MODE_MAPPING
)
from src.utilities.graph_utils import (
    filter_node_ids_by_type,
    get_downstream_dependencies,
    get_node_ids_from_structured_nodes,
)

logger = logging.getLogger(__name__)

def run(args: Namespace):
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
        logger.debug(f"Running with the following arguments: {args}")
        cache = CacheManager()
        cache.start_report("run", args)
        target_graph = DbtGraph(args)
                
        # Look for cache
        prev_cache = cache.get_cache()
        if prev_cache is None: # Should we exit here instead of compiling?
            logger.error("No cache found, please run 'dbt-ci init' first to generate the necessary manifest files and cache for comparison.")
            return
        logger.info("Cache successfully found - using cached state for comparison")

        changed_nodes_dict = {
            "modified_nodes": get_node_ids_from_structured_nodes(prev_cache.get("modified_nodes", None)) or [],
            "new_nodes": get_node_ids_from_structured_nodes(prev_cache.get("new_nodes", None)) or [],
            "deleted_nodes": get_node_ids_from_structured_nodes(prev_cache.get("deleted_nodes", None)) or []
        }
        changed_nodes = [value for values in changed_nodes_dict.values() for value in values]

        if len(changed_nodes) == 0:
            logger.info("No modified, new, or deleted nodes found in cache, skipping...")
            sys.exit(0)
        
        logger.info("\n-------------------------------------------------------")
        logger.info(f"Found {len(changed_nodes)} modified model(s):")
        for node in changed_nodes:
            string = f"  • {node.split('.')[-1]}"
            if node in changed_nodes_dict["deleted_nodes"]:
                string += " [Deleted]"
            elif node in changed_nodes_dict["modified_nodes"]:
                string += " [Modified]"
            elif node in changed_nodes_dict["new_nodes"]:
                string += " [New]"
            
            logger.info(string)
        logger.info("-------------------------------------------------------\n")

        run_with_mode(
            mode=getattr(args, "nodes", "all"),
            args=args,
            target_graph=target_graph,
            changed_nodes_dict=changed_nodes_dict,
            changed_nodes=changed_nodes
        )

        cache.update_report("run", "completed")
        logger.info("\nAll done!")
    except Exception as e:
        cache.update_report("run", "failed", comment=str(e))
        print_exception(e)
        sys.exit(1)

def run_with_mode(
    mode: RunModes,
    args: Namespace,
    target_graph: DbtGraph,
    changed_nodes_dict: dict[str, list[str]],
    changed_nodes: list[str]
):
    """Run modified nodes with specific dbt command based on mode"""
    try:
        runner_config = RunnerConfig(args.__dict__)
        run_order = ["seed", "run", "test", "snapshot"]
        if mode != "all":
            run_order = [MODE_MAPPING[mode]]

        for command in run_order:
            logger.info(f"\nIdentifying modified nodes of type: {REVERSE_MODE_MAPPING[command]}")
            node_type = NODE_TYPE_COMMAND_MAPPING[REVERSE_MODE_MAPPING[command]]

            # Get downstream dependencies for this node type
            set_of_downstream_dependencies = get_downstream_dependencies(
                dependency_graph=target_graph.to_dict(),
                node_ids=changed_nodes,  # All modified, new, deleted
                node_type=node_type
            )
            # Convert to list (function returns set or None)
            downstream_dependencies = list(set_of_downstream_dependencies) if set_of_downstream_dependencies else []

            # Combine all nodes that need to run (modified + new + downstream)
            # Skip deleted since they can't be run, but we still want to include their downstream dependencies 
            # to make sure they function without the deleted node
            nodes_to_run = filter_node_ids_by_type(
                dependency_graph=target_graph.to_dict(),
                node_type=node_type, # seeds, models, snapshots, tests
                node_ids=list(set(chain(
                    changed_nodes_dict.get("modified_nodes", []),
                    changed_nodes_dict.get("new_nodes", []),
                    downstream_dependencies # includes downstream dependencies of modified, new & deleted nodes
                )))
            )

            # If the user specified additional filters
            # dbt-ci run -m tests -f snapshots --> 
            # This should run modified tests and their snapshot dependencies only, not all downstream dependencies
            if getattr(args, "filters", None):
                if node_type != "test":
                    logger.warning(f"Filters are currently only supported for test mode. Ignoring filters for {REVERSE_MODE_MAPPING[command]}...")
                    continue
                else:
                    # When filters are provided in test mode, include upstream dependencies but only of types specified in filters
                    # Example: -f snapshots means include upstream snapshot dependencies of the changed tests
                    nodes_to_run = run_test_with_additional_filter(
                        dependency_graph=target_graph.to_dict(),
                        node_type=node_type,
                        args=args,
                        node_ids=list(set(chain(
                            changed_nodes_dict.get("modified_nodes", []),
                            changed_nodes_dict.get("new_nodes", []),
                            downstream_dependencies # includes downstream dependencies of modified, new & deleted nodes
                        )))
                    )

            if len(nodes_to_run) == 0:
                logger.info(f"No {REVERSE_MODE_MAPPING[command]} to run")
                continue

            modified_of_type = [n for n in changed_nodes_dict.get("modified_nodes", []) if n in nodes_to_run]
            new_of_type = [n for n in changed_nodes_dict.get("new_nodes", []) if n in nodes_to_run]
            downstream_of_type = [n for n in downstream_dependencies if n in nodes_to_run]

            # Display what will run, categorized by change type
            logger.info("\n-------------------------------------------------------")
            logger.info(f"The following {REVERSE_MODE_MAPPING[command]} will be run:")
            for node in modified_of_type:
                logger.info(f"  • [Modified] {node}")

            for node in new_of_type:
                logger.info(f"  • [New] {node}")

            for node in downstream_of_type:
                logger.info(f"  • [Downstream] {node}")
            logger.info(f"\nTotal {REVERSE_MODE_MAPPING[command]} to run: {len(nodes_to_run)}")
            logger.info("-------------------------------------------------------\n")

            logger.info(f"\n[{REVERSE_MODE_MAPPING[command].upper()}] - Running nodes...")
            if runner_config.get("dry_run", False):
                logger.info("DRY RUN: Command would be executed")
                continue

            result = run_dbt_command(
                command_args=append_dbt_variables_to_command([command, "--select", " ".join(nodes_to_run)], args),
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

def run_test_with_additional_filter(
    dependency_graph: DependencyGraph,
    node_type: DependencyGraphNodeType,
    args: Namespace,
    node_ids: list[str]
) -> list[str] | None:
    """Apply additional filters to the list of node IDs based on user input."""
    converted_filter = [NODE_TYPE_COMMAND_MAPPING[f] for f in getattr(args, "filters", [])]
    final_nodes: Set[str] = set()
    filtered_nodes = filter_node_ids_by_type(
        dependency_graph=dependency_graph,
        node_type=node_type,
        node_ids=node_ids
    )

    for node_id in filtered_nodes:
        node_metadata = dependency_graph.get("test", {}).get(node_id, {})
        if not node_metadata:
            continue
        # Continue if we have found the item
        upstream_dependencies_by_type = node_metadata.get("upstream_dependencies", {}).get("dependencies_by_type", {})
        if not upstream_dependencies_by_type:
            continue
        # Check if any of the dependencies match the filters
        for dep_type in upstream_dependencies_by_type.keys():
            if dep_type in converted_filter and len(upstream_dependencies_by_type[dep_type]) > 0:
                final_nodes.add(node_id)
                break

    print(f"Filtering nodes by types {getattr(args, 'filters', [])} resulted in {len(final_nodes)} nodes to run")
    print(final_nodes)

    return list(final_nodes)