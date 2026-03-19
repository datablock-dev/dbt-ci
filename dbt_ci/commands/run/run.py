"""Run command for dbt-ci"""

import sys
import logging
from argparse import Namespace
from itertools import chain
from typing import cast
from dbt_ci.graph.dependency_graph import DbtGraph
from dbt_ci.runners import run_dbt_command, append_dbt_variables_to_command
from dbt_ci.graph.graph_utils import filter_node_ids_by_type, get_upstream_dependencies, get_downstream_dependencies
from dbt_ci.schema import (
    RunModes,
    RunnerConfig,
    DependencyGraph,
    DependencyGraphNodeType,
    NODE_TYPE_COMMAND_MAPPING,
    REVERSE_MODE_MAPPING
)

logger = logging.getLogger(__name__)

def run_with_mode(
    args: Namespace,
    command: RunModes,
    nodes_to_run: list[str]    
) -> None:
    logger.info(f"\n[{REVERSE_MODE_MAPPING[command].upper()}] - Running nodes...")
    if getattr(args, "dry_run", False):
        logger.info("DRY RUN: Command would be executed")
        return

    result = run_dbt_command(
        command_args=append_dbt_variables_to_command([cast(str, command), "--select", " ".join(nodes_to_run)], args),
        runner_config=cast(RunnerConfig, args.__dict__)
    )

    if result and result.returncode == 0:
        logger.info(f"\n✅ Successfully ran {len(nodes_to_run)} {REVERSE_MODE_MAPPING[command]}(s)")
    else:
        logger.error("\n❌ Run failed")
        sys.exit(1)

def seeds(
    target_graph: DbtGraph,
    changed_nodes_dict: dict[str, list[str]]
) -> list[str]:
    """Run modified seeds"""
    upstream_seeds_of_changed_nodes = list(get_upstream_dependencies(
        dependency_graph=target_graph.to_dict(),
        node_type=["seed"],
        node_ids=list(chain(
            changed_nodes_dict.get("modified_nodes", []),
            changed_nodes_dict.get("new_nodes", [])
        )),
    ) or [])

    nodes_to_run = filter_node_ids_by_type(
        dependency_graph=target_graph.to_dict(),
        node_type=["seed"], # seeds, models, snapshots, tests
        node_ids=list(set(chain(
            changed_nodes_dict.get("modified_nodes", []),
            changed_nodes_dict.get("new_nodes", []),
            upstream_seeds_of_changed_nodes # seeds that modified/new nodes depend on
        )))
    )

    return nodes_to_run

def tests(
    target_graph: DbtGraph,
    changed_nodes_dict: dict[str, list[str]],
    changed_nodes: list[str],
    args: Namespace
) -> list[str]:
    """Get modified/new tests and downstream tests of changed nodes.
    
    If filters are provided, only include tests whose upstream dependencies
    match the specified filter types (e.g. -f snapshots).
    """
    downstream_test_dependencies = list(
        get_downstream_dependencies(
            dependency_graph=target_graph.to_dict(),
            node_ids=changed_nodes,
            node_type="test"
        ) or []
    )

    node_ids = list(set(chain(
        changed_nodes_dict.get("modified_nodes", []),
        changed_nodes_dict.get("new_nodes", []),
        downstream_test_dependencies
    )))

    if getattr(args, "filters", None):
        return _tests_with_filter(
            dependency_graph=target_graph.to_dict(),
            node_type="test",
            args=args,
            node_ids=node_ids
        )

    return filter_node_ids_by_type(
        dependency_graph=target_graph.to_dict(),
        node_type=["test"],
        node_ids=node_ids
    )


def _tests_with_filter(
    dependency_graph: DependencyGraph,
    node_type: DependencyGraphNodeType,
    args: Namespace,
    node_ids: list[str]
) -> list[str]:
    """Apply upstream-dependency filters to narrow down which tests to run.
    
    Only includes tests that have at least one upstream dependency matching
    one of the specified filter types.
    """
    converted_filter = [NODE_TYPE_COMMAND_MAPPING[f] for f in getattr(args, "filters", [])]
    final_nodes: set[str] = set()

    filtered_nodes = filter_node_ids_by_type(
        dependency_graph=dependency_graph,
        node_type=[node_type],
        node_ids=node_ids
    )

    for node_id in filtered_nodes:
        node_metadata = dependency_graph.get("test", {}).get(node_id, {})
        if not node_metadata:
            continue
        upstream_dependencies_by_type = node_metadata.get("upstream_dependencies", {}).get("dependencies_by_type", {})
        if not upstream_dependencies_by_type:
            continue
        for dep_type, dep_nodes in upstream_dependencies_by_type.items():
            if dep_type in converted_filter and isinstance(dep_nodes, (list, set)) and len(dep_nodes) > 0:
                final_nodes.add(node_id)
                break

    logger.debug(f"Filtering nodes by types {getattr(args, 'filters', [])} resulted in {len(final_nodes)} nodes to run")
    return list(final_nodes)