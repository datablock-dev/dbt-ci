"""Central dispatcher for running dbt commands across different runners."""
import os
import sys
from argparse import Namespace
from subprocess import CompletedProcess
from typing import Callable, Dict, List, Optional
from src.schema import RunnerConfig, Runners
from src.runners.dbt import dbt_runner
from src.runners.local import local_runner
from src.runners.docker import docker_runner
from src.runners.bash import bash_runner

RUNNERS: Dict[Runners, Callable[[List[str], RunnerConfig], CompletedProcess | None]] = {
    "local": local_runner,
    "dbt": dbt_runner,
    "docker": docker_runner,
    "bash": bash_runner
}

def run_dbt_command(
    command_args: List[str],
    runner_config: RunnerConfig
) -> CompletedProcess | None:
    """
    Central dispatcher for running dbt commands across any runner.
    
    Handles:
    - Runner routing (local, docker, bash)
    - Path resolution based on runner requirements
    - Consistent error handling
    
    Args:
        command_args: dbt command arguments (e.g., ['ls', '--select', 'state:modified+'])
        runner_config: Configuration containing runner type, paths, and runner-specific settings
        dry_run: Override config dry_run setting
        quiet: Override config quiet setting
    
    Returns:
        CompletedProcess from subprocess, or None if dry_run
    
    Example:
        config = {
            'runner': 'local',
            'dbt_project_dir': 'dbt',
            'prod_manifest_dir': 'dbt/.dbtstate',
            ...
        }
        output = run_dbt_command(['ls', '--select', 'state:modified+'], config)
    """
    runner = runner_config['runner']
    if runner in RUNNERS:
        return RUNNERS[runner](command_args, runner_config)

    print(f"Unsupported runner: {runner}")
    sys.exit(1)

def append_dbt_variables_to_command(
    command_args: List[str],
    variables: Namespace,
    skip_target: bool = False,
) -> List[str]:
    """Append dbt variables to command arguments."""
    commands = command_args.copy()
    dbt_variables = {
        "target": "--target",
        "vars": "--vars",
        "dbt_project_dir": "--project-dir",
        "profiles_dir": "--profiles-dir",
    }

    for var, dbt_flag in dbt_variables.items():
        if skip_target and var == "target":
            continue  # Skip adding target if skip_target is True
        if dbt_flag in commands:
            continue  # Skip if already in command args

        value = getattr(variables, var, None)
        if value is not None and value != "":
            commands.extend([str(dbt_flag), str(value)])

    return commands

def _get_absolute_path(path: str) -> str:
    """Convert path to absolute if it's relative."""
    if not path:
        return path
    return os.path.abspath(path) if not os.path.isabs(path) else path
