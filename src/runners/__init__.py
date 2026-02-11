"""Central dispatcher for running dbt commands across different runners."""
import os
from pathlib import Path
import subprocess
import sys
import venv
from argparse import Namespace
from subprocess import CompletedProcess
import tempfile
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
        if runner == "dbt" and dbt_version_exists is False:
            print(f"dbt version {runner_config.get('dbt_version')} not found. Installing...")
            run_with_dbt_version(runner_config.get('dbt_version'))
        return RUNNERS[runner](command_args, runner_config)

    print(f"Unsupported runner: {runner}")
    sys.exit(1)

def run_with_dbt_version(version: str):
    """Run a block of code with a specific dbt version in a temporary virtual environment."""
    with tempfile.TemporaryDirectory() as tmp:
        venv_dir = Path(tmp) / "venv"
        venv.create(venv_dir, with_pip=True)

        pip = venv_dir / "bin" / "pip"
        python = venv_dir / "bin" / "python"

        subprocess.run([pip, "install", f"dbt-core=={version}"], check=True)
        subprocess.run([python, "-m", "dbt", "--version"], check=True)

def dbt_version_exists(version: str) -> bool:
    """Check if a virtual environment for the specified dbt version already exists."""
    venv_path = Path.home() / ".cache" / "dbt-ci" / "venvs" / f"dbt-{version}"
    return venv_path.exists()


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
