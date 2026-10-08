"""
This module implements the bash runner for executing dbt commands using a custom dbt binary or script. It provides functionality to resolve dbt command arguments based on the provided variables and runner configuration.
"""
import os
import sys
import shlex
import logging
from typing import List
import subprocess
from subprocess import CompletedProcess
from dbt_ci.utilities.logging import setup_logging
from dbt_ci.schema import RunnerConfig

logger = logging.getLogger(__name__)

# Shells that need the dbt entrypoint passed through `-c` rather than dbt's arguments
SHELL_INTERPRETERS = {"bash", "sh", "zsh", "dash", "ksh"}

def bash_runner(
    commands: list[str],
    runner_config: RunnerConfig
) -> CompletedProcess | None:
    """
    Execute dbt commands using a custom dbt binary/script.
    
    Args:
        commands: The dbt command and arguments to run (e.g., ['dbt', 'ls', '--select', ...])
        shell_path: Path to the custom dbt executable to use (e.g., 'bin/dbt', '/usr/local/bin/dbt')
        dry_run: If True, only print the command
        quiet: If True, suppress stdout
    
    Note: if shell_path is a plain shell (e.g. /bin/bash), the entrypoint is run through
    it with `-c`; otherwise shell_path is treated as a dbt wrapper script.
    """
    setup_logging(runner_config.get('log_level', 'INFO'))
    shell_path = runner_config['shell_path']
    if os.path.basename(shell_path) in SHELL_INTERPRETERS:
        # A plain shell (the default /bin/bash) cannot take dbt arguments itself, so it
        # runs the entrypoint instead. A wrapper script receives the dbt arguments directly.
        entrypoint = runner_config.get('entrypoint') or 'dbt'
        commands = [shell_path, "-c", shlex.join([entrypoint, *commands])]
    else:
        commands = [shell_path] + commands
    
    if not runner_config.get('quiet', False):
        logger.debug(f"Running command: {' '.join(commands)}")
    
    if runner_config.get('dry_run', False):
        logger.info("DRY RUN: Command would be executed")
        return None
    
    try:
        result = subprocess.run(
            args=commands,
            check=True,
            capture_output=True,
            text=True
        )

        if not runner_config.get('quiet', False):
            print(result.stdout)

        # dbt writes warnings and its own log lines to stderr on successful runs, so
        # only the exit code (enforced by check=True above) decides success/failure.
        if result.stderr:
            logger.warning(result.stderr)

        return result
    except subprocess.CalledProcessError as e:
        if e.stderr:
            logger.error(e.stderr)
        if e.stdout:
            logger.error(e.stdout)
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)