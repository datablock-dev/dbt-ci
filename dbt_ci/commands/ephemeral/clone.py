from itertools import chain
import sys
import logging
from argparse import Namespace
from typing import cast
from dbt_ci.graph.dependency_graph import DbtGraph
from dbt_ci.graph.graph_utils import filter_node_ids_by_type, get_downstream_dependencies, get_upstream_dependencies
from dbt_ci.schema import RunnerConfig
from dbt_ci.utilities.logging import print_exception
from dbt_ci.utilities.paths import get_profile
from dbt_ci.runners import resolve_dbt_commands, run_dbt_command

logger = logging.getLogger(__name__)

def clone_command(
    changed_nodes_dict: dict[str, list[str]],
    args: Namespace
) -> None:
    """
        Helper function to run the dbt command that will create the ephemeral models based on the selected nodes.
        
        Please observe that we only clone models and snapshots, even if tests are modified.
        This is because Dbt only creates ephemeral versions of models and snapshots.
    """
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

        descendants = list(get_downstream_dependencies(target_graph.to_dict(), changed_nodes) or set())

        dependent_nodes = list(set(chain(
            # 1. 1st level ancestors of all descendants of changed nodes.
            #    Descendants need their direct parents cloned to execute correctly.
            get_upstream_dependencies(
                dependency_graph=target_graph.to_dict(),
                node_ids=descendants,
                node_type=["model", "snapshot"]
            ) or set(),
            # 2. 1st level ancestors of any tests or snapshots in changed nodes.
            #    Tests/snapshots reference their direct parents which must be available.
            get_upstream_dependencies(
                dependency_graph=target_graph.to_dict(),
                node_ids=filter_node_ids_by_type(target_graph.to_dict(), changed_nodes, ["test", "snapshot"]),
                node_type=["model", "snapshot"]
            ) or set()
        )))

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