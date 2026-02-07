"""Central dispatcher for running dbt commands across different runners."""
import os
import sys
from subprocess import CompletedProcess
from typing import List, Optional
from src.schema import RunnerConfig
from src.runners.dbt import dbt_runner
from src.runners.local import local_runner
from src.runners.docker import docker_runner
from src.runners.bash import bash_runner


def _get_absolute_path(path: str) -> str:
    """Convert path to absolute if it's relative."""
    if not path:
        return path
    return os.path.abspath(path) if not os.path.isabs(path) else path


def run_dbt_command(
    command_args: List[str],
    runner_config: RunnerConfig,
    dry_run: Optional[bool] = None,
    quiet: Optional[bool] = None
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
    use_dry_run = dry_run if dry_run is not None else runner_config.get('dry_run', False)
    use_quiet = quiet if quiet is not None else runner_config.get('quiet', False)
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
            dry_run=use_dry_run,
            quiet=use_quiet
        )
    elif runner == "dbt":
        # Direct dbt runner: uses dbt Python API
        # Remove entrypoint from command (dbt API doesn't want "dbt" as first arg)
        dbt_command = command_args if not entrypoint else full_command[1:]
        
        return dbt_runner(
            dbt_command,
            dry_run=use_dry_run,
            quiet=use_quiet
        )
    elif runner == "bash":
        # Bash runner: pass paths as-is, let the script handle translation
        return bash_runner(
            commands=full_command,
            dry_run=use_dry_run,
            shell_path=runner_config['shell_path'],
            quiet=use_quiet
        )
    
    elif runner == "docker":
        # Docker runner: needs absolute paths for volume mounts
        # Remove entrypoint from command (docker runner adds it back)
        docker_command = command_args if not entrypoint else full_command[1:]
        
        return docker_runner(
            commands=docker_command,
            dbt_project_dir=_get_absolute_path(runner_config['dbt_project_dir']),
            profiles_dir=_get_absolute_path(runner_config['profiles_dir']) if runner_config.get('profiles_dir') else None,
            state_dir=_get_absolute_path(runner_config['prod_manifest_dir']),
            docker_image=runner_config.get('docker_image', 'ghcr.io/dbt-labs/dbt-core:latest'),
            docker_platform=runner_config.get('docker_platform'),
            docker_volumes=runner_config.get('docker_volumes', []),
            docker_env=runner_config.get('docker_env', []),
            docker_network=runner_config.get('docker_network', 'host'),
            docker_user=runner_config.get('docker_user'),
            docker_args=runner_config.get('docker_args', ''),
            dry_run=use_dry_run,
            quiet=use_quiet
        )
    
    else:
        print(f"Unsupported runner: {runner}")
        sys.exit(1)
