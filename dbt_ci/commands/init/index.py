"""
This module contains the implementation of the `init` command for the dbt CI tool.
"""

import json
import sys
import logging
from argparse import Namespace
from typing import cast
import click
from dbt_ci.utilities.logging import print_exception
from dbt_ci.utilities.cache import CacheManager
from dbt_ci.dbt.dbt_commands import DbtCommands
from dbt_ci.graph.dependency_graph import DbtGraph
from dbt_ci.connectors import init_storage_connector
from dbt_ci.commands.init.state_modified import StateModified
from dbt_ci.graph.graph_utils import get_downstream_dependencies, get_node
from dbt_ci.schema import DependencyGraphNode, StateChangeSummary
from dbt_ci.utilities.paths import get_manifest_file, get_reference_manifest_file
from dbt_ci.commands.init.resolve_manifest import resolve_manifest_file_from_storage

logger = logging.getLogger(__name__)

def init(args: Namespace):
    """
    Initialize the dbt CI tool with necessary configuration and setup.
    This step compiles the DBT project to ensure that we have a generated manifest.json
    required for the tool to work.

    The tool by default compiles the DBT project with production settings but can be overriden.
    The tool generates two manifest.json files:
    1. The reference manifest.json with target equal to the current target
    2. "Production" reference manifest.json with target equal to the production target (if specified and different from current target)
    """
    try:
        # Convert kwargs to Namespace and resolve configuration
        # Variables class handles type conversions (tuples->lists, string->bool, etc.)
        click.secho("DBT CI Initialization", fg="green", bold=True)
        logger.debug(f"Running with the following arguments: {args}")
        dbt_commands = DbtCommands(args)
        cache = CacheManager(args)
        state_modified = StateModified(args)
        cache.clear_cache() # Clear cache at the start of init to avoid stale data issues
        cache.start_report("init", args)
        dbt_project_dir = getattr(args, "dbt_project_dir", None)
        reference_target = getattr(args, "reference_target", None)
        reference_state_path: str | None = getattr(args, "reference_state", None)
        resolved_storage = init_storage_connector(getattr(args, "state_uri", None))

        # Exit if dbt_project_dir is not provided
        if dbt_project_dir is None:
            logger.error("No dbt_project_dir specified. Please provide the path to your DBT project using the --dbt-project-dir argument.")
            sys.exit(1)

        if resolved_storage is not None:
            local_state_dir = resolve_manifest_file_from_storage(resolved_storage, args)
            # Update reference_state to use the local path where manifest was downloaded
            setattr(args, "reference_state", str(local_state_dir))

            # Reload reference manifest file after downloading from storage
            cache.write_reference_manifest(get_reference_manifest_file(str(local_state_dir)))
        
        # Compile dbt and generate reference manifest.json file
        #run_multiprocessed
        dbt_commands.reference_compile()

        target_manifest_file = get_manifest_file(dbt_project_dir)
        state_change_summary = state_modified.get_state_modified()
        cache.write_cache(state_change_summary)

        if reference_target and reference_target != getattr(args, "target", None):
            # Different targets - will compile again later with actual target
            cache.write_target_manifest(target_manifest_file)
        else:
            # Same target or no reference target specified - reference and target are the same
            logger.debug("Reference target is the same as current target!")
            logger.debug("Using the same manifest for both reference and target state.")
            cache.write_reference_manifest(target_manifest_file)
            cache.write_target_manifest(target_manifest_file)

        # Will generate summary and output it in the logs. It also covers:
        # 1. Migration plan for partitioning changes
        # 2. Ephemeral plan
        init_summary(state_change_summary, args)

        # Deleted-node dependency validation is left to dbt: compiling the project
        # already fails when a ref()/source() points at a node removed in this change
        # set. Re-enable the call below if standalone reporting is ever needed.
        # detect_deleted_models_with_downstream_dependencies(state_change_summary, args)

        # Compile with the actual target (not reference target)
        # Use the user-specified target, or let dbt use the default from dbt_project.yml
        dbt_commands.target_compile()

        cache.update_report(command="init", status="completed")
        logger.info("Initialization complete. Cache updated with current state(s).")
        logger.info("You can now run `dbt-ci run --mode <mode>` to execute modified models based on the generated state.")
    except Exception as e:
        cache = CacheManager(args)
        cache.update_report(command="init", status="failed")
        print_exception(e, "Error during initialization")
        sys.exit(1)

def init_summary(state_change_summary: StateChangeSummary, args: Namespace) -> None:
    """
        The following method will call the following steps to generate a summary of changes,
        but also migration, ephemeral:
        1. Generate summary of modified, deleted, and new nodes with their resource types
        2. Generate migration plan for modified nodes with partitioning changes
        3. Generate ephemeral plan for modified nodes with non-partitioning changes
    """
    #slack = SlackClient(args)
    #migration_map = generate_migration_map(args, cache)
    #ephemeral_map = generate_ephemeral_map(args, cache)

    logger.info("\n------------------------------------------------------")
    logger.info("State Change Summary:")
    for change_type, values in state_change_summary.items():
        values = cast(dict[str, DependencyGraphNode], values)
        if values is None or len(values) == 0:
            logger.info(f"\n{change_type.replace('_', ' ').title()}: 0")
            continue

        total_count = sum(len(node_dict) for node_dict in values.values())
        logger.info(f"\n{change_type.replace('_', ' ').title()}: {total_count}")
        for node_dict in values.values():
            for node in node_dict.values():
                node = cast(DependencyGraphNode, node)
                logger.info(f"  • {node['name']} [{node['resource_type']}]")
    logger.info("\n------------------------------------------------------")

    slack_webhook = getattr(args, "slack_webhook", None)
    if not slack_webhook:
        return

    try:
        from dbt_ci.notifications.slack import SlackClient
        header = "*DBT CI Initialization Summary:*\n\n"
        message = "*State Change Summary:*\n"
        message += json.dumps(state_change_summary, indent=2, default=lambda o: list(o) if isinstance(o, set) else str(o))
        message += "\n\n"
        SlackClient(args).send_message(header, message)
    except Exception as e:
        logger.error(f"Failed to send Slack message: {e}")

def detect_deleted_models_with_downstream_dependencies(
    state_change_summary: StateChangeSummary,
    args: Namespace
) -> None:
    """
    Detect nodes that still depend on nodes deleted in this change set.

    For every deleted node we resolve its downstream dependencies (the nodes that
    consume it) from the reference graph and build a mapping of each surviving
    dependent to the specific deleted node(s) it relies on, so the report can name
    exactly which deleted node breaks each dependent.
    """
    deleted_nodes = state_change_summary.get("deleted_nodes", None)

    # If there are no deleted nodes, we can skip this step entirely
    if deleted_nodes is None or len(deleted_nodes) == 0:
        return

    reference_graph = DbtGraph(args, is_reference=True)
    reference_dict = reference_graph.to_dict()

    # deleted_nodes is structured as {type: {short_name: node_data}} — flatten to a set of short names
    deleted_node_ids = {
        node_name
        for node_type_nodes in deleted_nodes.values()
        for node_name in node_type_nodes.keys()
    }

    # Map each surviving dependent -> the deleted node(s) it depends on. Resolving
    # downstream dependencies one deleted node at a time preserves the attribution
    # that a single flattened union would otherwise lose.
    dependents_to_deleted: dict[str, set[str]] = {}
    for deleted_node_id in deleted_node_ids:
        downstream_dependencies = get_downstream_dependencies(
            dependency_graph=reference_dict,
            node_ids=[deleted_node_id]
        )
        if not downstream_dependencies:
            continue

        for dependent_id in downstream_dependencies:
            # Skip downstream nodes that are themselves deleted — those are safe to ignore
            if dependent_id in deleted_node_ids:
                continue
            dependents_to_deleted.setdefault(dependent_id, set()).add(deleted_node_id)

    if not dependents_to_deleted:
        return

    logger.error("\n------------------------------------------------------")
    click.secho("Deleted Nodes with Downstream Dependencies Detected:", fg="red", bold=True)
    for dependent_id in sorted(dependents_to_deleted):
        node = get_node(reference_dict, dependent_id)
        resource_type = node.get("resource_type", "unknown") if node else "unknown"
        deleted_deps = ", ".join(sorted(dependents_to_deleted[dependent_id]))
        logger.error(f"  • {dependent_id} ({resource_type}) depends on deleted node(s): {deleted_deps}")
    logger.error("------------------------------------------------------\n")
    logger.error("Please review the above nodes and consider deleting them or modifying them to remove dependencies on deleted nodes.")
    # Advisory only — dbt's own compile is the source of truth for broken references,
    # so this check reports the finding without failing the run.