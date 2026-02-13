"""
This module contains the implementation of the `init` command for the dbt CI tool.
"""

import json
import sys
import logging
from pathlib import Path
from argparse import Namespace
from typing import Tuple
import click
from src.connectors import init_storage_connector
from src.dependency_graph import DbtGraph
from src.utilities.paths import get_manifest_file
from src.schema import RunnerConfig, StorageConnectorConfig
from src.variables import Variables
from src.cache import CacheManager
from src.runners import resolve_dbt_commands, run_dbt_command, append_dbt_variables_to_command
from src.utilities.graph_utils import (
    get_deleted_nodes,
    get_new_nodes,
    get_nodes,get_structured_modified_nodes
)

logger = logging.getLogger(__name__)

def init(**kwargs):
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
        args = Namespace(**kwargs)
        cache = CacheManager()
        config = Variables(args)
        variables = config.to_namespace()
        reference_target = getattr(variables, "reference_target", None)
        command = ["compile"]
        resolved_storage = init_storage_connector(variables)

        if resolved_storage is not None:
            resolve_manifest_file_from_storage(resolved_storage)

        if reference_target is None:
            logger.warning("No reference target specified, using current target as production state for comparison.")
        else:
            command.extend(["--target", reference_target])

        run_dbt_command(
            command_args=resolve_dbt_commands(command, variables, True),
            runner_config=RunnerConfig(variables.__dict__),
        )

        logger.info("DBT project compiled successfully. manifest.json generated.")
        target_graph = DbtGraph(variables)
        reference_graph = DbtGraph(variables, is_production=True)

        ls_output = run_dbt_command(
            command_args=resolve_dbt_commands(["ls", "--select", "state:modified", "--output", "name", "--quiet"], variables),
            runner_config=RunnerConfig(variables.__dict__)
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
            "modified_nodes": get_structured_modified_nodes(get_nodes(reference_graph_dict, modified_nodes)),
            "deleted_nodes": get_structured_modified_nodes(get_nodes(reference_graph_dict, get_deleted_nodes(reference_graph_dict, target_graph_dict))),
            "new_nodes": get_structured_modified_nodes(get_nodes(target_graph_dict, get_new_nodes(reference_graph_dict, target_graph_dict)))
        }

        target_manifest_file = get_manifest_file(variables.dbt_project_dir)

        # Write cache
        cache.write_cache(state_change_summary)
        cache.write_cache(target_manifest_file, "reference_manifest.json" if reference_target else "target_manifest.json")

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
        logger.info("------------------------------------------------------\n")

        if reference_target is not None:
            run_dbt_command(
                command_args=append_dbt_variables_to_command(command, variables),
                runner_config=RunnerConfig(variables.__dict__)
            )

            target_manifest_file = get_manifest_file(variables.dbt_project_dir)
            cache.write_cache(target_manifest_file, "target_manifest.json")

        logger.info("Initialization complete. Cache updated with current state(s).")
        logger.info("You can now run `dbt-ci run --mode <mode>` to execute modified models based on the generated state.")
    except Exception as e:
        logger.error(f"Error during initialization: {str(e)}")
        sys.exit(1)

def resolve_manifest_file_from_storage(
    resolved_storage: Tuple[StorageConnectorConfig, str],
    variables: Namespace
) -> None:
    """Download manifest file from storage and save to local path for graph generation."""
    cwd = Path.cwd()
    storage_connector, state_uri = resolved_storage
    logger.info(f"Using storage connector '{storage_connector}' for state management with URI: {state_uri}")
    reference_manifest = storage_connector["download"](state_uri)
    dbtstate_dir: str | None = None

    # Write and download manifest to path
    if variables.reference_state is None:
        dbtstate_dir = cwd / variables.dbt_project_dir / ".dbtstate" # Default
    else:
        dbtstate_dir = cwd / variables.state
    if dbtstate_dir is None:
        logger.error("No valid path found for downloading manifest file. Please specify a valid --state path or ensure your dbt_project_dir is correct.")
        sys.exit(1)

    Path(dbtstate_dir).mkdir(parents=True, exist_ok=True)
    manifest_path = dbtstate_dir / "manifest.json"
            
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(reference_manifest, indent=2))
    logger.info(f"Reference manifest successfully downloaded and saved to {manifest_path}")
