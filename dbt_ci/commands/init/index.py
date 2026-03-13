"""
This module contains the implementation of the `init` command for the dbt CI tool.
"""

import json
import sys
import logging
from pathlib import Path
from argparse import Namespace
from typing import cast
import click
from dbt_ci.graph.dependency_graph import DbtGraph
from dbt_ci.cache import CacheManager
from dbt_ci.logging import print_exception
from dbt_ci.connectors import init_storage_connector
from dbt_ci.graph.graph_utils import get_downstream_dependencies
from dbt_ci.commands.init.state_modified import StateModified, get_state_modified
from dbt_ci.utilities.paths import get_manifest_file, get_reference_manifest_file
from dbt_ci.schema import DependencyGraphNode, StateChangeSummary, StorageConnectorConfig
from dbt_ci.utilities.dbt_commands import dbt_command_reference_compile, dbt_command_target_compile

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
        cache = CacheManager(args)
        state_modified = StateModified(args)
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
            if reference_state_path is None:
                logger.error("State URI provided without a reference state path. Please specify a local path for the reference state using --reference-state or --state when using remote state storage.")
                sys.exit(1)

            local_state_dir = resolve_manifest_file_from_storage(resolved_storage, args)
            # Update reference_state to use the local path where manifest was downloaded
            setattr(args, "reference_state", str(local_state_dir))
            
            # Reload reference manifest file after downloading from storage
            cache.write_reference_manifest(get_reference_manifest_file(reference_state_path))
        
        # Compile dbt and generate reference manifest.json file
        dbt_command_reference_compile(args)

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

        # This method has issues and needs to be resolved before being reintroduced
        detect_deleted_models_with_downstream_dependencies(state_change_summary, args)

        # Compile with the actual target (not reference target)
        # Use the user-specified target, or let dbt use the default from dbt_project.yml
        dbt_command_target_compile(args)

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
                logger.info(f"  • {node['name']} ({node['resource_type']})")
    logger.info("\n------------------------------------------------------")

    try:
        header = "*DBT CI Initialization Summary:*\n\n"

        message = "*State Change Summary:*\n"
        message += json.dumps(state_change_summary, indent=2)
        message += "\n\n"
        #slack.send_message(header, message)
    except Exception as e:
        logger.error(f"Failed to send Slack message: {e}")

def resolve_manifest_file_from_storage(
    resolved_storage: tuple[StorageConnectorConfig, str],
    args: Namespace
) -> Path:
    """Download manifest file from storage and save to local path for graph generation.
    
    Returns:
        Path: The local directory path where the manifest was saved
    """
    cwd = Path.cwd()
    storage_connector, state_uri = resolved_storage
    logger.info(f"Using storage connector '{storage_connector.get('name', 'Unknown')}' for state management with URI: {state_uri}")
    reference_manifest = storage_connector["download"](state_uri)
    dbtstate_dir: Path | None = None
    dbt_project_dir = getattr(args, "dbt_project_dir", None)
    reference_state = getattr(args, "reference_state", None)

    if dbt_project_dir is None:
        logger.error("No dbt_project_dir specified. Please provide the path to your DBT project using the --dbt-project-dir argument.")
        sys.exit(1)

    # Write and download manifest to path
    # When using Docker, always use the local dbt_project_dir/.dbtstate path on host
    if getattr(args, "runner", None) == "docker" or reference_state is None:
        dbtstate_dir = cwd / dbt_project_dir / ".dbtstate" # Default
    else:
        dbtstate_dir = cwd / reference_state

    if dbtstate_dir is None:
        logger.error("No valid path found for downloading manifest file. Please specify a valid --state path or ensure your dbt_project_dir is correct.")
        sys.exit(1)

    Path(dbtstate_dir).mkdir(parents=True, exist_ok=True)
    manifest_path = dbtstate_dir / "manifest.json"

    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(reference_manifest, indent=2))
    logger.info(f"Reference manifest successfully downloaded and saved to {manifest_path}")

    return dbtstate_dir

def detect_deleted_models_with_downstream_dependencies(
    state_change_summary: StateChangeSummary,
    args: Namespace
) -> None:
    """Detect deleted models and their downstream dependencies to generate a delete map."""
    deleted_nodes = state_change_summary.get("deleted_nodes", None)
    reference_graph = DbtGraph(args, is_reference=True)
    
    # If there are no deleted nodes, we can skip this step entirely
    if deleted_nodes is None or len(deleted_nodes) == 0:
        return
    
    # Deleted nodes detected, lets proceed and identify downstream dependencies
    downstream_dependencies = get_downstream_dependencies(
        dependency_graph=reference_graph.to_dict(),
        node_ids=list(deleted_nodes.keys())
    )

    if downstream_dependencies is None or len(downstream_dependencies) == 0:
        return
    
    logger.error("\n------------------------------------------------------")
    click.secho("Deleted Nodes with Downstream Dependencies Detected:", fg="red", bold=True)
    for node_id in downstream_dependencies:
        logger.error(f"  • {node_id} ({deleted_nodes[node_id]['resource_type']}) depends on deleted node(s)")
    logger.error("------------------------------------------------------\n")
    logger.error("Please review the above nodes and consider deleting them or modifying them to remove dependencies on deleted nodes.")
    logger.error("Exiting...")
    sys.exit(1)