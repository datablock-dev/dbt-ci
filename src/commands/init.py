"""
This module contains the implementation of the `init` command for the dbt CI tool.
"""

import json
import sys
import logging
from pathlib import Path
from argparse import Namespace
from typing import Any, cast
import click
from src import dependency_graph
from src.adapters.slack import SlackClient
from src.commands.ephemeral import generate_ephemeral_map
from src.commands.migration import generate_migration_map
from src.dependency_graph import DbtGraph
from src.cache import CacheManager
from src.schema import RunnerConfig, StateChangeSummary, StorageConnectorConfig
from src.logging import print_exception
from src.connectors import init_storage_connector
from src.utilities.paths import get_manifest_file, get_reference_manifest_file
from src.runners import resolve_dbt_commands, run_dbt_command
from src.utilities.graph_utils import (
    filter_node_ids_by_multiple_types,
    get_deleted_nodes,
    get_downstream_dependencies,
    get_new_nodes,
    get_nodes,get_structured_modified_nodes
)

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
        cache = CacheManager()
        cache.start_report("init", args)
        reference_target = getattr(args, "reference_target", None)
        reference_vars = getattr(args, "reference_vars", None)
        reference_state_path: str | None = getattr(args, "reference_state", None)
        command = ["compile"]
        resolved_storage = init_storage_connector(getattr(args, "state_uri", None))

        if resolved_storage is not None:
            if reference_state_path is None:
                logger.error("State URI provided without a reference state path. Please specify a local path for the reference state using --reference-state or --state when using remote state storage.")
                sys.exit(1)

            local_state_dir = resolve_manifest_file_from_storage(resolved_storage, args)
            # Update reference_state to use the local path where manifest was downloaded
            setattr(args, "reference_state", str(local_state_dir))
            # Reload reference manifest file after downloading from storage
            args.reference_manifest_file = get_reference_manifest_file(reference_state_path)
            cache.write_cache(get_reference_manifest_file(reference_state_path), "reference_manifest.json")

        if reference_target is None:
            logger.warning("No reference target specified, using current target as reference state for comparison.")
        else:
            command.extend(["--target", reference_target])
            command.extend(["--vars", reference_vars]) if reference_vars else None

        run_dbt_command(
            command_args=resolve_dbt_commands(
                command_args=command, 
                args=args, 
                ignore_keys=["vars", "target"] # Don't pass vars or target when compiling reference manifest
            ),
            runner_config=RunnerConfig(args.__dict__),
        )

        logger.info("DBT project compiled successfully. manifest.json generated.")
        dbt_project_dir = getattr(args, "dbt_project_dir", None)
        if dbt_project_dir is None:
            logger.error("No dbt_project_dir specified. Please provide the path to your DBT project using the --dbt-project-dir argument.")
            sys.exit(1)
        
        target_manifest_file = get_manifest_file(dbt_project_dir)
        target_graph = DbtGraph(args)
        reference_graph = DbtGraph(args, is_production=True)

        state_change_summary = get_state_change_summary(args, target_graph, reference_graph)

        if reference_target is not None and reference_target != getattr(args, "target", None):
            # Different targets - will compile again later with actual target
            cache.write_cache(target_manifest_file, "target_manifest.json")
        else:
            # Same target or no reference target specified - reference and target are the same
            logger.debug("Reference target is the same as current target, using the same manifest for both reference and target state.")
            cache.write_cache(target_manifest_file, "reference_manifest.json")
            cache.write_cache(target_manifest_file, "target_manifest.json")

        # Will generate summary and output it in the logs. It also covers:
        # 1. Migration plan for partitioning changes
        # 2. Ephemeral plan
        init_summary(state_change_summary, args, cache)
        detect_deleted_models_with_downstream_dependencies(state_change_summary, args)

        # Compile with the actual target (not reference target)
        # Use the user-specified target, or let dbt use the default from dbt_project.yml
        skip_target_compile = getattr(args, "skip_target_compile", False)
        is_reference_target_same_as_current = reference_target is None or reference_target == getattr(args, "target", None)
        if skip_target_compile is False and not is_reference_target_same_as_current:
            target_command = ["compile"]
            actual_target = getattr(args, "target", None)
            if actual_target and actual_target != "default":
                target_command.extend(["--target", actual_target])
            # If no target specified, dbt will use the default from dbt_project.yml
            run_dbt_command(
                command_args=resolve_dbt_commands(target_command, args),
                runner_config=RunnerConfig(args.__dict__)
            )
            target_manifest_file = get_manifest_file(args.dbt_project_dir)
            cache.write_cache(cast(dict[str, Any], target_manifest_file), "target_manifest.json")

        cache.update_report(command="init", status="completed")
        logger.info("Initialization complete. Cache updated with current state(s).")
        logger.info("You can now run `dbt-ci run --mode <mode>` to execute modified models based on the generated state.")
    except Exception as e:
        cache.update_report(command="init", status="failed")
        print_exception(e, "Error during initialization")
        sys.exit(1)

def get_state_change_summary(
    args: Namespace,
    target_graph: DbtGraph,
    reference_graph: DbtGraph,
) -> StateChangeSummary:
    cache = CacheManager()

    commands = resolve_dbt_commands(["ls", "--select", "state:modified", "--output", "name", "--quiet"], args)
    commands.extend(["--target", getattr(args, "reference_target")])
    commands.extend(["--vars", getattr(args, "reference_vars")]) if getattr(args, "reference_vars", None) else None

    ls_output = run_dbt_command(
        command_args=commands,
        runner_config=RunnerConfig(args.__dict__)
    )

    if ls_output is None:
        logger.info("No modified nodes found during initialization. Exiting...")
        cache.write_cache({
            "modified_nodes": None,
            "deleted_nodes": None,
            "new_nodes": None
        })
        sys.exit(0)

    modified_nodes = ls_output.stdout.splitlines()
    target_graph_dict = target_graph.to_dict()
    reference_graph_dict = reference_graph.to_dict()

    new_node_ids = set(get_new_nodes(reference_graph_dict, target_graph_dict) or [])
    deleted_node_ids = set(get_deleted_nodes(reference_graph_dict, target_graph_dict) or [])
    truly_modified_nodes = [n for n in modified_nodes if n not in new_node_ids and n not in deleted_node_ids]

    state_change_summary: StateChangeSummary = {
        "modified_nodes": get_structured_modified_nodes(get_nodes(
            dependency_graph=target_graph_dict, 
            node_ids=truly_modified_nodes
        )),
        "deleted_nodes": get_structured_modified_nodes(get_nodes(
            dependency_graph=reference_graph_dict, 
            node_ids=list(deleted_node_ids)
        )),
        "new_nodes": get_structured_modified_nodes(get_nodes(
            dependency_graph=target_graph_dict, 
            node_ids=list(new_node_ids)
        ))
    }

    # Write cache
    cache.write_cache(cast(dict, state_change_summary))

    return state_change_summary

def init_summary(
    state_change_summary: StateChangeSummary,
    args: Namespace,
    cache: CacheManager
) -> None:
    """
        The following method will call the following steps to generate a summary of changes,
        but also migration, ephemeral:
        1. Generate summary of modified, deleted, and new nodes with their resource types
        2. Generate migration plan for modified nodes with partitioning changes
        3. Generate ephemeral plan for modified nodes with non-partitioning changes
    """
    slack = SlackClient(args)
    migration_map = generate_migration_map(args, cache)
    ephemeral_map = generate_ephemeral_map(args, cache)

    logger.info("\n------------------------------------------------------")
    logger.info("State Change Summary:")
    for change_type, values in state_change_summary.items():
        if values is None or len(values) == 0:
            logger.info(f"\n{change_type.replace('_', ' ').title()}: 0")
            continue

        total_count = sum(len(node_dict) for node_dict in values.values())
        logger.info(f"\n{change_type.replace('_', ' ').title()}: {total_count}")
        for node_dict in values.values():
            for node in node_dict.values():
                logger.info(f"  • {node['name']} ({node['resource_type']})")
    logger.info("\n------------------------------------------------------")
    logger.info("Ephemeral Plan:")
    if len(ephemeral_map) == 0:
        logger.info("No non-partitioning changes detected that require an ephemeral environment.")
    else:
        for node_id, node_info in ephemeral_map.items():
            target_table_id = f"{node_info['ephemeral_config']['database']}.{node_info['ephemeral_config']['schema']}.{node_info['ephemeral_config']['name']}" if node_info['ephemeral_config'] else "N/A"
            reference_table_id = f"{node_info['reference_config']['database']}.{node_info['reference_config']['schema']}.{node_info['reference_config']['name']}" if node_info['reference_config'] else "N/A"

            logger.info(f"Model: {node_id}")
            logger.info(f"  - Ephemeral Target: {target_table_id}")
            logger.info(f"  - Reference Target: {reference_table_id}")
    logger.info("\n------------------------------------------------------")
    logger.info("Migration Plan:")
    if len(migration_map["nodes"]) == 0:
        logger.info("No partitioning changes detected.")
    else:
        for node_id, node_info in migration_map["nodes"].items():
            logger.info("Model: %s", node_id)
            logger.info("  - Table ID: %s", node_info.get("table_id"))
            logger.info("  - Old Partitioning: %s", node_info.get("old_partitioning"))
            logger.info("  - New Partitioning: %s", node_info.get("new_partitioning"))
    logger.info("------------------------------------------------------\n")

    try:
        header = "*DBT CI Initialization Summary:*\n\n"

        message = "*State Change Summary:*\n"
        message += json.dumps(state_change_summary, indent=2)
        message += "\n\n"

        message += "*Migration Plan:*\n"
        message += json.dumps(migration_map, indent=2)
        message += "\n\n"

        message += "*Ephemeral Plan:*\n"
        message += json.dumps(ephemeral_map, indent=2)
        slack.send_message(header, message)
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
    reference_graph = DbtGraph(args, is_production=True)
    
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