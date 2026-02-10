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
    runner_config: RunnerConfig,
    dry_run: Optional[bool] = None,
    quiet: bool = True
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
    entrypoint = runner_config.get('entrypoint', 'dbt')
    
    # Handle empty entrypoint (means no command prefix)
    if entrypoint == '':
        entrypoint = None
    
    # Build full command with entrypoint
    full_command = [*([entrypoint] if entrypoint else []), *command_args]
    
    if runner == "local":
        # Local runner: use absolute paths for reliability
        # Replace paths in command with absolute versions
        absolute_command = []
        path_flags = {'--state', '--project-dir', '--profiles-dir', '--target-path', '--log-path'}
        prev_arg = None
        
        for arg in full_command:
            if prev_arg in path_flags and isinstance(arg, str):
                absolute_command.append(_get_absolute_path(arg))
            else:
                absolute_command.append(arg)
            prev_arg = arg
        
        return local_runner(
            absolute_command,
            runner_config=runner_config
        )
    elif runner == "dbt":
        # Direct dbt runner: uses dbt Python API
        # Remove entrypoint and use absolute paths (same as local runner)
        dbt_command_args = command_args if not entrypoint else full_command[1:]
        
        # Convert paths to absolute for reliability
        absolute_command = []
        path_flags = {'--state', '--project-dir', '--profiles-dir', '--target-path', '--log-path'}
        prev_arg = None
        
        for arg in dbt_command_args:
            if prev_arg in path_flags and isinstance(arg, str):
                absolute_command.append(_get_absolute_path(arg))
            else:
                absolute_command.append(arg)
            prev_arg = arg
        
        return dbt_runner(
            absolute_command,
            runner_config=runner_config
        )
    elif runner == "bash":
        # Bash runner: pass paths as-is, let the script handle translation
        return bash_runner(
            commands=full_command,
            runner_config=runner_config
        )
    elif runner == "docker":
        # Docker runner: needs absolute paths for volume mounts
        # Remove entrypoint from command (docker runner adds it back)
        docker_command = command_args if not entrypoint else full_command[1:]
        
        return docker_runner(
            commands=docker_command,
            runner_config=runner_config
        )
    else:
        print(f"Unsupported runner: {runner}")
        sys.exit(1)

def append_dbt_variables_to_command(
    command_args: List[str],
    variables: Namespace
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
