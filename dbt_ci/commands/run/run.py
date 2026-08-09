"""Run command for dbt-ci"""

import sys
import logging
from argparse import Namespace
from itertools import chain
from typing import cast
from dbt_ci.graph.dependency_graph import DbtGraph
from dbt_ci.runners import run_dbt_command, resolve_dbt_commands
from dbt_ci.graph.graph_utils import (
    filter_node_ids_by_type,
    get_downstream_dependencies,
    get_display_name,
    get_selectors,
    get_upstream_dependencies,
)
from dbt_ci.schema import (
    RunModes,
    RunnerConfig,
    DependencyGraph,
    DependencyGraphNodeType,
    NODE_TYPE_COMMAND_MAPPING,
    REVERSE_MODE_MAPPING,
    MODE_MAPPING, 
)

logger = logging.getLogger(__name__)

def run_nodes(
    args: Namespace,
    target_graph: DbtGraph,
    changed_nodes: list[str],
    changed_nodes_dict: dict[str, list[str]]  
) -> None:
    try:
        mode: RunModes = getattr(args, "nodes", "all")
        run_order: list[str] = ["seed", "run", "test", "snapshot"]
        if mode != "all" and mode in MODE_MAPPING:
            run_order = cast(list[str], [MODE_MAPPING[mode]])

        command_fn_map = {
            "seed": seeds,
            "run": models,
            "test": tests,
            "snapshot": snapshots,
        }

        for command in run_order:
            fn = command_fn_map.get(command)
            if fn is None:
                continue
            nodes_to_run = fn(
                target_graph=target_graph,
                changed_nodes_dict=changed_nodes_dict,
                changed_nodes=changed_nodes,
                args=args
            )

            if nodes_to_run is None or len(nodes_to_run) == 0:
                logger.info(f"No nodes to run for {command}, skipping...")
                continue

            # Print information
            logger.info(f"\n[{REVERSE_MODE_MAPPING[command].upper()}] - Running nodes...")
            log_nodes_to_run(nodes_to_run, changed_nodes_dict, target_graph)

            if getattr(args, "dry_run", False):
                logger.info("DRY RUN: Command would be executed")
                continue

            selectors = get_selectors(target_graph.to_dict(), nodes_to_run)
            if not selectors:
                logger.info(f"No resolvable selectors for {command}, skipping...")
                continue

            result = run_dbt_command(
                command_args=resolve_dbt_commands([cast(str, command), "--select", " ".join(selectors)], args),
                runner_config=cast(RunnerConfig, args.__dict__)
            )

            if result and result.returncode == 0:
                logger.info(f"\n✅ Successfully ran {len(nodes_to_run)} {REVERSE_MODE_MAPPING[command]}(s)")
            else:
                logger.error("\n❌ Run failed")
                sys.exit(1)
    except Exception as e:
        logger.error(f"\n❌ Error running dbt command: {e}")
        sys.exit(1)

def seeds(
    target_graph: DbtGraph,
    changed_nodes_dict: dict[str, list[str]],
    changed_nodes: list[str],
    args: Namespace
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

def snapshots(
    target_graph: DbtGraph,
    changed_nodes_dict: dict[str, list[str]],
    changed_nodes: list[str],
    args: Namespace
) -> list[str]:
    """Run snapshots"""
    downstream_snapshot_dependencies = list(
        get_downstream_dependencies(
            dependency_graph=target_graph.to_dict(),
            node_ids=changed_nodes,
            node_type="snapshot"
        ) or []
    )

    return filter_node_ids_by_type(
        dependency_graph=target_graph.to_dict(),
        node_type=["snapshot"],
        node_ids=list(set(chain(
            changed_nodes_dict.get("modified_nodes", []),
            changed_nodes_dict.get("new_nodes", []),
            downstream_snapshot_dependencies
        )))
    )
    

def models(
    target_graph: DbtGraph,
    changed_nodes_dict: dict[str, list[str]],
    changed_nodes: list[str],
    args: Namespace
) -> list[str]:
    """Run modified/new models and downstream models of changed nodes."""
    downstream_model_dependencies = list(
        get_downstream_dependencies(
            dependency_graph=target_graph.to_dict(),
            node_ids=changed_nodes,
            node_type="model"
        ) or []
    )

    return filter_node_ids_by_type(
        dependency_graph=target_graph.to_dict(),
        node_type=["model"],
        node_ids=list(set(chain(
            changed_nodes_dict.get("modified_nodes", []),
            changed_nodes_dict.get("new_nodes", []),
            downstream_model_dependencies
        )))
    )


def log_nodes_to_run(
    nodes_to_run: list[str],
    changed_nodes_dict: dict[str, list[str]],
    target_graph: DbtGraph | None = None,
) -> None:
    """Print the nodes about to run, grouped by why they were selected."""
    mapping = {
        "new": set(),
        "modified": set(),
        "deleted": set(),
        "dependency": set()
    }

    for node in nodes_to_run:
        if node in changed_nodes_dict.get("modified_nodes", []):
            mapping["modified"].add(node)
        elif node in changed_nodes_dict.get("new_nodes", []):
            mapping["new"].add(node)
        elif node in changed_nodes_dict.get("deleted_nodes", []):
            mapping["deleted"].add(node)
        else:
            mapping["dependency"].add(node)


    logger.info("\n-------------------------------------------------------")
    logger.info(f"Found {len(nodes_to_run)} node(s) to run:")

    graph = target_graph.to_dict() if target_graph else None
    for type, nodes in mapping.items():
        if len(nodes) == 0:
            continue
        logger.info(f"\n{type.upper()} NODES:")
        for node in sorted(nodes):
            logger.info(f"  • {get_display_name(graph, node)}")
    logger.info("-------------------------------------------------------\n")