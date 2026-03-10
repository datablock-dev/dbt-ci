from itertools import chain
import sys
import logging
from argparse import Namespace
from typing import cast
from dbt_ci.graph.dependency_graph import DbtGraph
from dbt_ci.graph.graph_utils import filter_node_ids_by_type, get_downstream_dependencies, get_upstream_dependencies
from dbt_ci.schema import RunnerConfig
from dbt_ci.logging import print_exception
from dbt_ci.utilities.paths import get_profile
from dbt_ci.runners import resolve_dbt_commands, run_dbt_command

logger = logging.getLogger(__name__)

def clone_command(
    changed_nodes_dict: dict[str, list[str]],
    args: Namespace
) -> None:
    """Helper function to run the dbt command that will create the ephemeral models based on the selected nodes."""
    def _filter_models_and_snapshots(target_graph: DbtGraph, node_ids: list[str]) -> list[str]:
        return filter_node_ids_by_type(
            dependency_graph=target_graph.to_dict(),
            node_type=["model", "snapshot"],
            node_ids=node_ids
        )

    try:
        node_selector: set[str] = set()
        profile = get_profile(args)
        threads = profile.get("threads", 5)
        target_graph = DbtGraph(args)

        changed_nodes = list(set(chain(
            changed_nodes_dict["modified_nodes"],
            changed_nodes_dict["new_nodes"]
        )))

        dependent_nodes = filter_node_ids_by_type(
            dependency_graph=target_graph.to_dict(),
            node_type=["model", "snapshot"],
            node_ids=list(chain(
                # 1. All downstream dependencies of any changed node (models, snapshots, tests, etc.)
                #    These need to be re-run to verify nothing downstream breaks.
                get_downstream_dependencies(target_graph.to_dict(), changed_nodes) or set(),
                # 2. Upstream models/snapshots of any changed test or snapshot.
                #    Tests reference models/snapshots upstream — those references must be available.
                #    Changed snapshots similarly need their upstream models/snapshots present.
                get_upstream_dependencies(
                    dependency_graph=target_graph.to_dict(), 
                    node_ids=filter_node_ids_by_type(target_graph.to_dict(), changed_nodes, ["test", "snapshot"]), 
                    node_type=["model", "snapshot"]
                ) or set(),
                # 3. Upstream models/snapshots of all changed nodes.
                #    Changed models need their own parents present to execute correctly.
                get_upstream_dependencies(target_graph.to_dict(), changed_nodes, ["model", "snapshot"]) or set()
            ))
        )

        ephemeral_nodes = list(set(chain(
            changed_nodes_dict["modified_nodes"],
            changed_nodes_dict["new_nodes"],
            dependent_nodes
        )))

        if len(ephemeral_nodes) == 0:
            logger.info("No nodes to create ephemeral environments for, skipping...")
            sys.exit(0)

        # We add all changed nodes + their downstream dependencies to the clone selection
        for node in _filter_models_and_snapshots(target_graph, changed_nodes):
            node_selector.add(f"{node}+")

        # Downstream dependencies need to be included and to have their
        # 1st level upstream dependencies included to ensure the graph can be built and run successfully        
        for node in _filter_models_and_snapshots(target_graph, dependent_nodes):
            node_selector.add(f"1+{node}")

        command = resolve_dbt_commands(
            command_args=["clone", "--select", *node_selector, "--threads", str(threads)],
            args=args
        )

        logger.debug(f"Running dbt clone command with arguments: {command}")

        if getattr(args, "dry_run", False):
            logger.info("Dry run enabled - no actual ephemeral environment will be created.")
            sys.exit(0)

        run_dbt_command(
            command_args=command,
            runner_config=cast(RunnerConfig, args.__dict__)
        )
    except Exception as e:
        logger.error(f"Error running dbt clone command: {str(e)}")
        print_exception(e)
        sys.exit(1)