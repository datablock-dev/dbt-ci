"""Central dispatcher for running dbt commands across different runners."""
import subprocess
import venv
import logging
from pathlib import Path
from argparse import Namespace
from typing import Callable, cast
from dbt_ci.schema import RunnerConfig, Runners
from dbt_ci.runners.dbt import dbt_runner
from dbt_ci.runners.local import local_runner
from dbt_ci.runners.docker import docker_runner, get_container_paths
from dbt_ci.runners.bash import bash_runner
from dbt_ci.utilities.paths import get_absolute_path

logger = logging.getLogger(__name__)

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
    if runner not in RUNNERS:
        raise ValueError(f"Unsupported runner: {runner}")

    dbt_binary = resolve_pinned_dbt_binary(runner_config)
    if dbt_binary is not None:
        # local_runner prefixes the command with `entrypoint`, so pointing it at the
        # pinned virtual environment's dbt is what actually makes the pin take effect.
        runner_config = cast(RunnerConfig, {**runner_config, "entrypoint": dbt_binary})

    return RUNNERS[runner](command_args, runner_config)

def resolve_pinned_dbt_binary(runner_config: RunnerConfig) -> str | None:
    """
    Return the path to a dbt binary satisfying --dbt-version/--adapter, or None.

    Only the `local` runner can execute an arbitrary dbt binary: the `dbt` runner
    invokes dbt in-process, `docker` takes its dbt from the image and `bash` from the
    user's shell script. For those runners a pin is reported as unsupported instead of
    being silently ignored.
    """
    dbt_version = runner_config.get("dbt_version")
    adapter = runner_config.get("adapter")
    if not dbt_version and not adapter:
        return None

    runner = runner_config.get("runner")
    if runner != "local":
        logger.warning(
            "--dbt-version/--adapter are only honoured by the 'local' runner; the '%s' "
            "runner resolves dbt from %s. Ignoring the pin.",
            runner,
            {
                "dbt": "the dbt-core installed alongside dbt-ci",
                "docker": "the configured --docker-image",
                "bash": "the configured --shell-path script",
            }.get(cast(str, runner), "its own environment"),
        )
        return None

    venv_dir = get_dbt_venv_dir(dbt_version, adapter)
    if not dbt_venv_is_ready(venv_dir):
        create_dbt_venv(venv_dir, dbt_version, adapter)

    return str(venv_dir / "bin" / "dbt")

def get_dbt_venv_dir(dbt_version: str | None, adapter: str | None) -> Path:
    """Return the cache directory holding the virtual environment for this version/adapter pair."""
    parts = [f"dbt-{dbt_version}" if dbt_version else "dbt-default"]
    if adapter:
        name, version = parse_adapter(adapter)
        parts.append(f"{name}-{version}" if version else name)
    return Path.home() / ".cache" / "dbt-ci" / "venvs" / "+".join(parts)

def dbt_venv_is_ready(venv_dir: Path) -> bool:
    """
    Check whether a cached virtual environment finished installing successfully.

    A sentinel file is used rather than the directory's existence so that an interrupted
    or failed install is rebuilt instead of being reused in a broken state.
    """
    return (venv_dir / ".dbt-ci-ready").is_file() and (venv_dir / "bin" / "dbt").is_file()

def create_dbt_venv(venv_dir: Path, dbt_version: str | None, adapter: str | None) -> None:
    """Create a virtual environment containing the requested dbt-core version and adapter."""
    packages: list[str] = []
    if dbt_version:
        packages.append(f"dbt-core=={dbt_version}")
    if adapter:
        name, version = parse_adapter(adapter)
        packages.append(f"{name}=={version}" if version else name)

    logger.info(f"Installing {', '.join(packages)} into {venv_dir}...")
    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    venv.create(venv_dir, with_pip=True, clear=True)

    pip = venv_dir / "bin" / "pip"
    dbt_bin = venv_dir / "bin" / "dbt"

    subprocess.run([str(pip), "install", *packages], check=True)
    subprocess.run([str(dbt_bin), "--version"], check=True)

    (venv_dir / ".dbt-ci-ready").write_text("\n".join(packages), encoding="utf-8")

def parse_adapter(adapter: str) -> tuple[str, str | None]:
    """
    Split an adapter specification into its package name and optional pinned version.

    Accepts 'dbt-bigquery', 'dbt-bigquery=1.10.0' and 'dbt-bigquery==1.10.0'.
    """
    name, separator, version = adapter.replace("==", "=").partition("=")
    name = name.strip()
    version = version.strip()

    if not name:
        raise ValueError(
            f"Invalid adapter format: '{adapter}'. Expected 'adapter' or 'adapter=version' "
            "(e.g. 'dbt-bigquery' or 'dbt-bigquery=1.10.0')."
        )

    if separator and not version:
        raise ValueError(
            f"Invalid adapter format: '{adapter}'. A version separator was given without a "
            "version (e.g. 'dbt-bigquery=1.10.0')."
        )

    return name, version or None

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
    
    # Commands such as `run-operation` reject some of these flags, so ignore_keys applies
    # to the path flags as well as to the variables and boolean flags below.
    if ignore_keys:
        path_flags = {var: flag for var, flag in path_flags.items() if var not in ignore_keys}

    # Local and dbt runners need absolute paths
    if runner in ["local", "dbt"]:
        for var, flag in path_flags.items():
            value = getattr(args, var, None)
            if value is not None and value != "":
                absolute_path = get_absolute_path(value)
                commands.extend([flag, absolute_path])

    # Docker runner needs container paths from docker-env
    elif runner == "docker":
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
        raise ValueError("Runner not specified")

    return commands
