"""
This module contains the implementation of the `init` command for the dbt CI tool.
"""

import json
import sys
import logging
from pathlib import Path
from argparse import Namespace
import click
from src.adapters.slack import SlackClient
from src.commands.ephemeral import generate_ephemeral_map
from src.commands.migration import generate_migration_map
from src.dependency_graph import DbtGraph
from src.cache import CacheManager
from src.schema import DependencyGraphNode, RunnerConfig, StorageConnectorConfig
from src.logging import print_exception
from src.connectors import init_storage_connector
from src.utilities.paths import get_manifest_file, get_reference_manifest_file
from src.runners import resolve_dbt_commands, run_dbt_command
from src.utilities.graph_utils import (
    get_deleted_nodes,
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
        command = ["compile"]
        resolved_storage = init_storage_connector(getattr(args, "state_uri", None))

        if resolved_storage is not None:
            local_state_dir = resolve_manifest_file_from_storage(resolved_storage, args)
            # Update reference_state to use the local path where manifest was downloaded
            args.reference_state = str(local_state_dir)
            # Reload reference manifest file after downloading from storage
            args.reference_manifest_file = get_reference_manifest_file(args.reference_state)
            cache.write_cache(get_reference_manifest_file(args.reference_state), "reference_manifest.json")

        if reference_target is None:
            logger.warning("No reference target specified, using current target as reference state for comparison.")
        else:
            command.extend(["--target", reference_target])
            command.extend(["--vars", args.reference_vars]) if args.reference_vars else None

        run_dbt_command(
            command_args=resolve_dbt_commands(command, args, ["vars", "target"]),  # Don't pass vars or target when compiling reference manifest
            runner_config=RunnerConfig(args.__dict__),
        )

        logger.info("DBT project compiled successfully. manifest.json generated.")
        target_manifest_file = get_manifest_file(args.dbt_project_dir)
        target_graph = DbtGraph(args)
        reference_graph = DbtGraph(args, is_production=True)

        ls_output = run_dbt_command(
            command_args=resolve_dbt_commands(["ls", "--select", "state:modified", "--output", "name", "--quiet"], args),
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

        state_change_summary = {
            "modified_nodes": get_structured_modified_nodes(get_nodes(
                dependency_graph=reference_graph_dict, 
                node_ids=modified_nodes
            )),
            "deleted_nodes": get_structured_modified_nodes(get_nodes(
                dependency_graph=reference_graph_dict, 
                node_ids=get_deleted_nodes(reference_graph_dict, target_graph_dict)
            )),
            "new_nodes": get_structured_modified_nodes(get_nodes(
                dependency_graph=target_graph_dict, 
                node_ids=get_new_nodes(reference_graph_dict, target_graph_dict)
            ))
        }

        # Write cache
        cache.write_cache(state_change_summary)
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

        # Compile with the actual target (not reference target)
        # Use the user-specified target, or let dbt use the default from dbt_project.yml
        if args.skip_target_compile is False and reference_target is not None and reference_target != getattr(args, "target", None):
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
            cache.write_cache(target_manifest_file, "target_manifest.json")

        cache.update_report(command="init", status="completed")
        logger.info("Initialization complete. Cache updated with current state(s).")
        logger.info("You can now run `dbt-ci run --mode <mode>` to execute modified models based on the generated state.")
    except Exception as e:
        cache.update_report(command="init", status="failed")
        print_exception(e, "Error during initialization")
        sys.exit(1)

def init_summary(
    state_change_summary: dict[str, dict[str, list[DependencyGraphNode]] | None],
    args: Namespace,
    cache: CacheManager
):
    """
        The following method will call the following steps to generate a summary of changes,
        but also migration, ephemeral:
        1. Generate summary of modified, deleted, and new nodes with their resource types
        2. Generate migration plan for modified nodes with partitioning changes
        3. Generate ephemeral plan for modified nodes with non-partitioning changes
    """
    slack = SlackClient()
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
            logger.info(f"Model: {node_id}")
            logger.info(f"  - Table ID: {node_info['table_id']}")
            logger.info(f"  - Old Partitioning: {node_info['old_partitioning']}")
            logger.info(f"  - New Partitioning: {node_info['new_partitioning']}")
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

    # Write and download manifest to path
    # When using Docker, always use the local dbt_project_dir/.dbtstate path on host
    if getattr(args, "runner", None) == "docker" or getattr(args, "reference_state", None) is None:
        dbtstate_dir = cwd / getattr(args, "dbt_project_dir", None) / ".dbtstate" # Default
    else:
        dbtstate_dir = cwd / getattr(args, "reference_state", None)
    if dbtstate_dir is None:
        logger.error("No valid path found for downloading manifest file. Please specify a valid --state path or ensure your dbt_project_dir is correct.")
        sys.exit(1)

    Path(dbtstate_dir).mkdir(parents=True, exist_ok=True)
    manifest_path = dbtstate_dir / "manifest.json"
            
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(reference_manifest, indent=2))
    logger.info(f"Reference manifest successfully downloaded and saved to {manifest_path}")
    
    return dbtstate_dir
