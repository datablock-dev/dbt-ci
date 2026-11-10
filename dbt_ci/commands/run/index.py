"""Run command for dbt-ci"""

import sys
import logging
from argparse import Namespace
import click
from dbt_ci.commands.run.run import run_nodes
from dbt_ci.commands.run.skip_test_only import find_test_only_changes
from dbt_ci.commands.run.selection import resolve_user_selection
from dbt_ci.graph.dependency_graph import DbtGraph
from dbt_ci.errors import DbtCiError
from dbt_ci.utilities.cache import CacheManager
from dbt_ci.dbt.flags import apply_cached_config
from dbt_ci.utilities.logging import print_exception, redact_namespace
from dbt_ci.graph.graph_utils import get_display_name, get_node_ids_from_structured_nodes

logger = logging.getLogger(__name__)

SKIPPED_REASON = "not rebuilt: only its tests changed (`--skip-test-only-changes`)"


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
        logger.debug(f"Running with the following arguments: {redact_namespace(args)}")
        cache = CacheManager(args)
        cache.start_report("run", args)
        apply_cached_config(args)
        target_graph = DbtGraph(args)

        # Look for cache
        prev_cache = cache.get_cache()
        if prev_cache is None:
            # Nothing was compared, so passing here would hide a skipped or failed init.
            raise DbtCiError(
                "No cache found, please run 'dbt-ci init' first to generate the necessary "
                "manifest files and cache for comparison."
            )
        logger.info("Cache successfully found - using cached state for comparison")

        changed_nodes_dict = {
            "modified_nodes": get_node_ids_from_structured_nodes(
                prev_cache.get("modified_nodes", None)
            )
            or [],
            "new_nodes": get_node_ids_from_structured_nodes(prev_cache.get("new_nodes", None))
            or [],
            "deleted_nodes": get_node_ids_from_structured_nodes(
                prev_cache.get("deleted_nodes", None)
            )
            or [],
        }
        if not any(changed_nodes_dict.values()):
            logger.info("No modified, new, or deleted nodes found in cache, skipping...")
            sys.exit(0)

        if getattr(args, "skip_test_only_changes", False):
            skip_test_only_nodes(args, target_graph, changed_nodes_dict)

        # Downstream lookups walk the target graph, where deleted nodes no longer exist.
        # A renamed generic test, for example, is a deleted id plus a new one; anything
        # that depended on a deleted node has changed itself and is already modified.
        changed_nodes = list(
            dict.fromkeys(changed_nodes_dict["modified_nodes"] + changed_nodes_dict["new_nodes"])
        )

        run_nodes(
            args=args,
            target_graph=target_graph,
            changed_nodes=changed_nodes,
            changed_nodes_dict=changed_nodes_dict,
            reasons=prev_cache.get("reasons") or {},
            user_selection=resolve_user_selection(args),
        )

        cache.update_report("run", "completed")
        logger.info("\nAll done!")
    except Exception as e:
        cache = CacheManager(args)
        cache.update_report("run", "failed", comment=str(e))
        print_exception(e, "❌ Run failed")
        sys.exit(1)


def skip_test_only_nodes(
    args: Namespace, target_graph: DbtGraph, changed_nodes_dict: dict[str, list[str]]
) -> None:
    """
    Drop modified nodes whose only change is to their tests from the change set.

    The changed tests stay in the change set and still run, while the node they check,
    and the nodes downstream of it, are not rebuilt. Mutates changed_nodes_dict.
    """
    skipped = find_test_only_changes(
        args, target_graph.to_dict(), changed_nodes_dict["modified_nodes"]
    )
    if not skipped:
        logger.info("--skip-test-only-changes: no node changed only in its tests.")
        return

    changed_nodes_dict["modified_nodes"] = [
        node_id for node_id in changed_nodes_dict["modified_nodes"] if node_id not in skipped
    ]
    # The report lists them as modified; say why they were not rebuilt
    CacheManager(args).add_reasons({node_id: SKIPPED_REASON for node_id in skipped})
    graph = target_graph.to_dict()
    logger.info(f"\nSkipping {len(skipped)} node(s) whose only change is to their tests:")
    for node_id in sorted(skipped):
        logger.info(f"  • {get_display_name(graph, node_id)}")

    if not getattr(args, "defer", False):
        logger.warning(
            "Tests of skipped nodes query them in the CI target. Without --defer they fail "
            "unless those tables already exist there (for example from 'dbt-ci ephemeral')."
        )
