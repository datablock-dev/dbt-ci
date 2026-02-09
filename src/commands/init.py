"""
This module contains the implementation of the `init` command for the dbt CI tool.
"""

import sys
from argparse import Namespace
import click
from src.dependency_graph import DbtGraph
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
        # Convert kwargs to Namespace for Variables resolution
        args = Namespace(**kwargs)
        cache = CacheManager()
        config = Variables(args)
        variables = config.to_namespace()
        production_target = getattr(variables, "production_target", None)
        command = ["compile"]
        # Handle docker_volumes and docker_env which come as tuples from Click
        if 'docker_volumes' in kwargs:
            args.docker_volumes = list(kwargs['docker_volumes']) if kwargs['docker_volumes'] else []
        if 'docker_env' in kwargs:
            args.docker_env = list(kwargs['docker_env']) if kwargs['docker_env'] else []

        if production_target is None:
            click.echo("WARNING! No production target specified, using current target as production state for comparison.")
        else:
            command.extend(["--target", production_target])

        run_dbt_command(
            command_args=append_dbt_variables_to_command(command, variables),
            runner_config=RunnerConfig(variables.__dict__),
            quiet=False
        )

        click.echo("DBT project compiled successfully. manifest.json generated.")
        graph = DbtGraph(variables)
        modified_nodes = graph.get_state_modified()
        #cache.write_cache(graph.to_dict(), "")

        cache.write_cache(
            data={
                "modified_nodes": modified_nodes,
            },
            file_name="dbt_ci_state.json"
        )

    except Exception as e:
        click.echo(f"Error during initialization: {str(e)}")
        sys.exit(1)