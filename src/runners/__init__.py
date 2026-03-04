"""Central dispatcher for running dbt commands across different runners."""
import subprocess
import sys
import venv
from pathlib import Path
from argparse import Namespace
from typing import Callable
from src.schema import RunnerConfig, Runners
from src.runners.dbt import dbt_runner
from src.runners.local import local_runner
from src.runners.docker import docker_runner
from src.runners.bash import bash_runner
from src.utilities.paths import get_absolute_path

RUNNERS: dict[Runners, Callable[[list[str], RunnerConfig], subprocess.CompletedProcess | None]] = {
    "local": local_runner,
    "dbt": dbt_runner,
    "docker": docker_runner,
    "bash": bash_runner
}

def run_dbt_command(
    command_args: list[str],
    runner_config: RunnerConfig
) -> subprocess.CompletedProcess | None:
    """
    Central dispatcher for running dbt commands across any runner.
    
    Handles:
    - Runner routing (local, docker, bash)
    - Path resolution based on runner requirements
    - Consistent error handling
    
    Args:
        command_args: dbt command arguments (e.g., ['ls', '--select', 'state:modified+'])
        runner_config: Configuration containing runner type, paths, and runner-specific settings
    Returns:
        CompletedProcess from subprocess, or None if dry_run
    
    Example:
        config = {
            'runner': 'local',
            'dbt_project_dir': 'dbt',
            'reference_state': 'dbt/.dbtstate',
            ...
        }
        output = run_dbt_command(['ls', '--select', 'state:modified+'], config)
    """
    runner = runner_config['runner']
    if runner in RUNNERS:
        if runner == "dbt" and not dbt_version_exists(runner_config.get('dbt_version')):
            print(f"dbt version {runner_config.get('dbt_version')} not found. Installing...")
            run_with_dbt_version(runner_config.get('dbt_version'))
        
        if runner_config.get("adapter") and not adapter_exists(runner_config.get("adapter")):
            print(f"Adapter {runner_config.get('adapter')} not found. Installing...")
            install_adapter(runner_config.get("adapter"))

        return RUNNERS[runner](command_args, runner_config)

    print(f"Unsupported runner: {runner}")
    sys.exit(1)

def run_with_dbt_version(version: str):
    """Create a persistent virtual environment with a specific dbt version."""
    venv_dir = Path.home() / ".cache" / "dbt-ci" / "venvs" / f"dbt-{version}"
    
    # Create cache directory if it doesn't exist
    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    
    # Create virtual environment
    venv.create(venv_dir, with_pip=True, clear=True)

    pip = venv_dir / "bin" / "pip"
    dbt_bin = venv_dir / "bin" / "dbt"

    # Install dbt-core
    subprocess.run([str(pip), "install", f"dbt-core=={version}"], check=True)
    
    # Verify installation
    subprocess.run([str(dbt_bin), "--version"], check=True)

def dbt_version_exists(version: str) -> bool:
    """Check if a virtual environment for the specified dbt version already exists."""
    venv_path = Path.home() / ".cache" / "dbt-ci" / "venvs" / f"dbt-{version}"
    return venv_path.exists()

def install_adapter(adapter: str):
    """Install the specified dbt adapter into the virtual environment."""
    adapter_list = adapter.split("=")
    adapter_name = adapter_list[0].strip()
    adapter_version = adapter_list[-1].strip()

    if adapter_name is None or adapter_version is None:
        print(f"Invalid adapter format: {adapter}. Expected format 'adapter=version' (e.g., 'postgres=1.0.0')")
        sys.exit(1)

    venv_path = Path.home() / ".cache" / "dbt-ci" / "venvs" / f"{adapter_name}-{adapter_version}"
    
    if not venv_path.exists():
        print(f"Installing adapter {adapter_name} version {adapter_version}...")
        venv.create(venv_path, with_pip=True, clear=True)
        pip = venv_path / "bin" / "pip"
        subprocess.run([str(pip), "install", f"{adapter_name}=={adapter_version}"], check=True)
    else:
        print(f"Adapter {adapter_name} version {adapter_version} already installed.")

def adapter_exists(adapter: str) -> bool:
    """Check if the specified dbt adapter is installed."""
    try:
        adapter_list = adapter.split("=")
        adapter_name = adapter_list[0].strip()
        adapter_version = adapter_list[-1].strip()

        if adapter_name is None or adapter_version is None:
            return False

        venv_path = Path.home() / ".cache" / "dbt-ci" / "venvs" / f"{adapter_name}-{adapter_version}"
        return venv_path.exists()
    except Exception as e:
        print(f"Error checking adapter existence: {e}")
        return False

def append_dbt_variables_to_command(
    command_args: list[str],
    args: Namespace,
    skip_target: bool = False,
) -> list[str]:
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

        value = getattr(args, var, None)
        if value is not None and value != "":
            commands.extend([str(dbt_flag), str(value)])

    return commands

# To replace append_dbt_variables_to_command
def resolve_dbt_commands(
    command_args: list[str],
    args: Namespace,
    ignore_keys: list[str] | None = None,
) -> list[str]:
    """Resolve dbt command arguments"""
    commands = command_args.copy()
    runner = getattr(args, "runner", None)
    
    # Regular dbt variables with values
    dbt_variables = {
        "target": "--target",
        "vars": "--vars",
    }
    
    # Boolean flags (no value needed)
    boolean_flags = {
        "defer": "--defer",
    }

    # Path mappings for different runners
    path_flags = {
        "dbt_project_dir": "--project-dir",
        "profiles_dir": "--profiles-dir",
        "reference_state": "--state",
    }
    
    # Local and dbt runners need absolute paths
    if runner in ["local", "dbt"]:
        for var, flag in path_flags.items():
            value = getattr(args, var, None)
            if value is not None and value != "":
                absolute_path = get_absolute_path(value)
                commands.extend([flag, absolute_path])
    
    # Docker runner needs container paths from docker-env
    elif runner == "docker":
        from src.runners.docker import get_container_paths
        
        # Use the shared function to get container path mappings
        container_path_map = get_container_paths(args.__dict__)
        
        for var, flag in path_flags.items():
            container_path = container_path_map.get(var)
            if container_path:
                commands.extend([flag, container_path])

    # Handle regular variables with values
    for var, dbt_flag in dbt_variables.items():
        if ignore_keys and var in ignore_keys:
            continue  # Skip adding variable if it's in the ignore_keys list
        if dbt_flag in commands:
            continue  # Skip if already in command args

        value = getattr(args, var, None)
        if value is not None and value != "":
            commands.extend([str(dbt_flag), str(value)])
    
    # Handle boolean flags (only add flag if True)
    for var, dbt_flag in boolean_flags.items():
        if ignore_keys and var in ignore_keys:
            continue  # Skip adding variable if it's in the ignore_keys list
        if dbt_flag in commands:
            continue  # Skip if already in command args
        
        value = getattr(args, var, None)
        if value is True:
            commands.append(dbt_flag)

    if runner is None:
        print("Runner not found! Exiting...")
        sys.exit(1)

    return commands
