"""
This module contains the implementation of the `init` command for the dbt CI tool.
"""

import sys
from argparse import Namespace
import click
from src.dependency_graph import DbtGraph
from src.parser import get_deleted_nodes, get_structured_modified_nodes
from src.paths import get_manifest_file
from src.schema import RunnerConfig
from src.variables import Variables
from src.cache import CacheManager
from src.runners import run_dbt_command, append_dbt_variables_to_command

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
        args = Namespace(**kwargs)
        cache = CacheManager()
        config = Variables(args)
        variables = config.to_namespace()
        production_target = getattr(variables, "production_target", None)
        command = ["compile"]

        if production_target is None:
            click.echo("WARNING! No production target specified, using current target as production state for comparison.")
        else:
            command.extend(["--target", production_target])

        run_dbt_command(
            command_args=append_dbt_variables_to_command(command, variables),
            runner_config=RunnerConfig(variables.__dict__)
        )

        click.echo("DBT project compiled successfully. manifest.json generated.")
        target_graph = DbtGraph(variables)
        reference_graph = DbtGraph(variables, user_production_state=True)
        modified_nodes = target_graph.get_state_modified()
        target_graph_dict = target_graph.to_dict()
        reference_graph_dict = reference_graph.to_dict()
        deleted_nodes = get_deleted_nodes(reference_graph_dict, target_graph_dict)
        x = get_structured_modified_nodes(
            dependency_graph=target_graph_dict,
            modified_nodes=modified_nodes
        )

        cache.write_cache({
            "modified_nodes": modified_nodes,
            "deleted_nodes": deleted_nodes
        })
        print(target_graph.get_nodes(modified_nodes))
        
        # Get manifest file
        target_manifest_file = get_manifest_file(variables.dbt_project_dir)
        cache.write_cache(target_manifest_file, "target_prod_manifest.json" if production_target else "target_manifest.json")

        if production_target is not None:
            run_dbt_command(
                command_args=append_dbt_variables_to_command(command, variables),
                runner_config=RunnerConfig(variables.__dict__)
            )

            target_manifest_file = get_manifest_file(variables.dbt_project_dir)
            cache.write_cache(target_manifest_file, "target_manifest.json")

        click.echo("Initialization complete. Cache updated with current state(s).")
        click.echo("You can now run `dbt-ci run --mode <mode>` to execute modified models based on the generated state.")

    except Exception as e:
        click.echo(f"Error during initialization: {str(e)}")
        sys.exit(1)