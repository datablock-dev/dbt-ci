"""Run command for dbt-ci"""

import logging
from argparse import Namespace
from datetime import datetime, timezone
from itertools import chain
from typing import cast
from dbt_ci.graph.dependency_graph import DbtGraph
from dbt_ci.commands.run.explain import explain_selection
from dbt_ci.commands.run.retry import get_retries, resolve_retry_command, run_results_marker
from dbt_ci.commands.run.selection import UserSelection
from dbt_ci.errors import DbtCommandError
from dbt_ci.runners import run_dbt_command, resolve_dbt_commands
from dbt_ci.utilities.cache import CacheManager
from dbt_ci.utilities.run_times import read_node_times
from dbt_ci.graph.graph_utils import (
    filter_node_ids_by_type,
    get_downstream_dependencies,
    get_display_name,
    get_node,
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

# dbt runs both data tests and unit tests (dbt >= 1.8) with `dbt test`
TEST_TYPES: list[DependencyGraphNodeType] = ["test", "unit_test"]


def run_nodes(
    args: Namespace,
    target_graph: DbtGraph,
    changed_nodes: list[str],
    changed_nodes_dict: dict[str, list[str]],
    reasons: dict[str, list[str]] | None = None,
    user_selection: UserSelection | None = None,
) -> None:
    """
    Build the selected seeds, snapshots, models and tests in order, stopping at a failure.

    reasons (from init's cache) explains why each changed node is in the run;
    user_selection (from --select / --exclude) narrows what each step builds.
    """
    mode: RunModes = getattr(args, "nodes", "all")
    # Snapshots run before models so that models built on a changed snapshot read
    # its new state, and tests run last once everything they check exists.
    run_order: list[str] = ["seed", "snapshot", "run", "test"]
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
            args=args,
        )

        if nodes_to_run and user_selection is not None:
            nodes_to_run, left_out = user_selection.split(nodes_to_run, target_graph.to_dict())
            if left_out:
                names = ", ".join(
                    sorted(get_display_name(target_graph.to_dict(), node) for node in left_out)
                )
                logger.info(
                    f"Leaving out of the {command} step by --select/--exclude "
                    f"({len(left_out)}): {names}"
                )

        if nodes_to_run is None or len(nodes_to_run) == 0:
            logger.info(f"No nodes to run for {command}, skipping...")
            continue

        # Print information
        logger.info(f"\n[{REVERSE_MODE_MAPPING[command].upper()}] - Running nodes...")
        log_nodes_to_run(nodes_to_run, changed_nodes_dict, target_graph, reasons)

        if getattr(args, "dry_run", False):
            logger.info("DRY RUN: Command would be executed")
            continue

        selectors = get_selectors(target_graph.to_dict(), nodes_to_run)
        if not selectors:
            logger.info(f"No resolvable selectors for {command}, skipping...")
            continue

        run_step(
            args, resolve_dbt_commands([cast(str, command), "--select", " ".join(selectors)], args)
        )
        logger.info(f"\n✅ Successfully ran {len(nodes_to_run)} {REVERSE_MODE_MAPPING[command]}(s)")


def run_step(args: Namespace, command_args: list[str]) -> None:
    """
    Run one step's dbt command, retrying it up to --retries times if it fails.

    A retry runs `dbt retry`, which reruns only the nodes that errored, failed or were
    skipped. If the failed command wrote no run_results.json of its own, there is
    nothing for dbt retry to resume, so the command itself runs again instead.
    """
    retries = get_retries(args)
    step_marker = run_results_marker(args)
    for attempt in range(retries + 1):
        # The runner raises DbtCommandError if dbt fails, which fails the run command.
        # The nodes that did run still cost time, so their times are kept either way.
        started = datetime.now(timezone.utc)
        try:
            run_dbt_command(
                command_args=command_args, runner_config=cast(RunnerConfig, args.__dict__)
            )
            return
        except DbtCommandError as e:
            if attempt == retries:
                raise
            if run_results_marker(args) != step_marker:
                command_args = resolve_retry_command(args)
                what = "its failed and skipped nodes with dbt retry"
            else:
                what = "it, as dbt wrote no results to retry from"
            logger.warning(f"{e}. Retrying {what} (retry {attempt + 1} of {retries})...")
        finally:
            record_run_times(args, started)


def record_run_times(args: Namespace, started: datetime) -> None:
    """Keep the execution time of each node the last dbt command ran, for the report."""
    dbt_project_dir = getattr(args, "dbt_project_dir", None)
    if not dbt_project_dir:
        return
    try:
        CacheManager(args).add_run_times(read_node_times(dbt_project_dir, started))
    except Exception as e:  # timings are informational and must never fail a run
        logger.debug(f"Could not record run times: {e}")


def get_downstream_depth(args: Namespace) -> int | None:
    """
    Return the configured downstream selection depth, or None for the full closure.

    A change to a central staging model otherwise selects every descendant, which on a
    real project means rebuilding almost everything - the opposite of what a
    change-based CI tool is for. Depth 0 runs only what changed.
    """
    depth = getattr(args, "downstream_depth", None)
    if depth is None:
        return None
    if depth < 0:
        logger.warning(
            f"Ignoring negative --downstream-depth ({depth}); selecting the full downstream graph."
        )
        return None
    return depth


def seeds(
    target_graph: DbtGraph,
    changed_nodes_dict: dict[str, list[str]],
    changed_nodes: list[str],
    args: Namespace,
) -> list[str]:
    """Run modified seeds"""
    upstream_seeds_of_changed_nodes = list(
        get_upstream_dependencies(
            dependency_graph=target_graph.to_dict(),
            node_type=["seed"],
            node_ids=list(
                chain(
                    changed_nodes_dict.get("modified_nodes", []),
                    changed_nodes_dict.get("new_nodes", []),
                )
            ),
        )
        or []
    )

    nodes_to_run = filter_node_ids_by_type(
        dependency_graph=target_graph.to_dict(),
        node_type=["seed"],  # seeds, models, snapshots, tests
        node_ids=list(
            set(
                chain(
                    changed_nodes_dict.get("modified_nodes", []),
                    changed_nodes_dict.get("new_nodes", []),
                    upstream_seeds_of_changed_nodes,  # seeds that modified/new nodes depend on
                )
            )
        ),
    )

    return nodes_to_run


def tests(
    target_graph: DbtGraph,
    changed_nodes_dict: dict[str, list[str]],
    changed_nodes: list[str],
    args: Namespace,
) -> list[str]:
    """Get modified/new tests and downstream tests of changed nodes.

    If filters are provided, only include tests whose upstream dependencies
    match the specified filter types (e.g. -f snapshots).
    """
    dependency_graph = target_graph.to_dict()
    depth = get_downstream_depth(args)
    downstream_test_dependencies: set[str] = set()
    for test_type in TEST_TYPES:
        downstream_test_dependencies.update(
            get_downstream_dependencies(
                dependency_graph=dependency_graph,
                node_ids=changed_nodes,
                node_type=test_type,
                levels=depth,
            )
            or []
        )

    if depth is not None:
        # A test sits one level below the node it checks, so the depth cap would drop
        # the tests of the deepest nodes this run builds. Select them explicitly.
        built_nodes = set(
            chain(
                seeds(target_graph, changed_nodes_dict, changed_nodes, args),
                snapshots(target_graph, changed_nodes_dict, changed_nodes, args),
                models(target_graph, changed_nodes_dict, changed_nodes, args),
            )
        )
        downstream_test_dependencies.update(get_tests_of_nodes(dependency_graph, built_nodes))

    node_ids = list(
        set(
            chain(
                changed_nodes_dict.get("modified_nodes", []),
                changed_nodes_dict.get("new_nodes", []),
                downstream_test_dependencies,
            )
        )
    )

    if getattr(args, "filters", None):
        return _tests_with_filter(
            dependency_graph=target_graph.to_dict(), node_type="test", args=args, node_ids=node_ids
        )

    return filter_node_ids_by_type(
        dependency_graph=dependency_graph, node_type=TEST_TYPES, node_ids=node_ids
    )


def get_tests_of_nodes(dependency_graph: DependencyGraph, node_ids: set[str]) -> set[str]:
    """Return the data and unit tests that check any of the given nodes."""
    if not node_ids:
        return set()
    test_ids: set[str] = set()
    for test_type in TEST_TYPES:
        for test_id, test_node in (dependency_graph.get(test_type) or {}).items():
            parents = test_node.get("upstream_dependencies", {}).get("node_dependencies") or set()
            if node_ids & set(parents):
                test_ids.add(test_id)
    return test_ids


def _tests_with_filter(
    dependency_graph: DependencyGraph,
    node_type: DependencyGraphNodeType,
    args: Namespace,
    node_ids: list[str],
) -> list[str]:
    """Apply upstream-dependency filters to narrow down which tests to run.

    Only includes tests that have at least one upstream dependency matching
    one of the specified filter types.
    """
    converted_filter = [NODE_TYPE_COMMAND_MAPPING[f] for f in getattr(args, "filters", [])]
    final_nodes: set[str] = set()

    filtered_nodes = filter_node_ids_by_type(
        dependency_graph=dependency_graph, node_type=TEST_TYPES, node_ids=node_ids
    )

    for node_id in filtered_nodes:
        node_metadata = get_node(dependency_graph, node_id)
        if not node_metadata:
            continue
        upstream_dependencies_by_type = node_metadata.get("upstream_dependencies", {}).get(
            "dependencies_by_type", {}
        )
        if not upstream_dependencies_by_type:
            continue
        for dep_type, dep_nodes in upstream_dependencies_by_type.items():
            if (
                dep_type in converted_filter
                and isinstance(dep_nodes, (list, set))
                and len(dep_nodes) > 0
            ):
                final_nodes.add(node_id)
                break

    logger.debug(
        f"Filtering nodes by types {getattr(args, 'filters', [])} resulted in {len(final_nodes)} "
        "nodes to run"
    )
    return list(final_nodes)


def snapshots(
    target_graph: DbtGraph,
    changed_nodes_dict: dict[str, list[str]],
    changed_nodes: list[str],
    args: Namespace,
) -> list[str]:
    """Run snapshots"""
    downstream_snapshot_dependencies = list(
        get_downstream_dependencies(
            dependency_graph=target_graph.to_dict(),
            node_ids=changed_nodes,
            node_type="snapshot",
            levels=get_downstream_depth(args),
        )
        or []
    )

    return filter_node_ids_by_type(
        dependency_graph=target_graph.to_dict(),
        node_type=["snapshot"],
        node_ids=list(
            set(
                chain(
                    changed_nodes_dict.get("modified_nodes", []),
                    changed_nodes_dict.get("new_nodes", []),
                    downstream_snapshot_dependencies,
                )
            )
        ),
    )


def models(
    target_graph: DbtGraph,
    changed_nodes_dict: dict[str, list[str]],
    changed_nodes: list[str],
    args: Namespace,
) -> list[str]:
    """Run modified/new models and downstream models of changed nodes."""
    downstream_model_dependencies = list(
        get_downstream_dependencies(
            dependency_graph=target_graph.to_dict(),
            node_ids=changed_nodes,
            node_type="model",
            levels=get_downstream_depth(args),
        )
        or []
    )

    return filter_node_ids_by_type(
        dependency_graph=target_graph.to_dict(),
        node_type=["model"],
        node_ids=list(
            set(
                chain(
                    changed_nodes_dict.get("modified_nodes", []),
                    changed_nodes_dict.get("new_nodes", []),
                    downstream_model_dependencies,
                )
            )
        ),
    )


def log_nodes_to_run(
    nodes_to_run: list[str],
    changed_nodes_dict: dict[str, list[str]],
    target_graph: DbtGraph | None = None,
    reasons: dict[str, list[str]] | None = None,
) -> None:
    """Print the nodes about to run, grouped by why they were selected, with the reason."""
    mapping: dict[str, set[str]] = {
        "new": set(),
        "modified": set(),
        "deleted": set(),
        "dependency": set(),
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
    changed_ids = set(
        chain(changed_nodes_dict.get("modified_nodes", []), changed_nodes_dict.get("new_nodes", []))
    )
    for type, nodes in mapping.items():
        if len(nodes) == 0:
            continue
        logger.info(f"\n{type.upper()} NODES:")
        for node in sorted(nodes):
            why = explain_selection(graph, node, changed_ids, reasons) if graph else ""
            logger.info(f"  • {get_display_name(graph, node)}" + (f": {why}" if why else ""))
    logger.info("-------------------------------------------------------\n")
