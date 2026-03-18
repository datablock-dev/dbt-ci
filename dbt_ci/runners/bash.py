"""
This module implements the bash runner for executing dbt commands using a custom dbt binary or script. It provides functionality to resolve dbt command arguments based on the provided variables and runner configuration.
"""
import sys
import logging
from typing import List
import subprocess
from subprocess import CompletedProcess
from dbt_ci.utilities.logging import setup_logging
from dbt_ci.schema import RunnerConfig

logger = logging.getLogger(__name__)

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
    
    Note: The first element 'dbt' in commands will be replaced with shell_path
    """
    setup_logging(runner_config.get('log_level', 'INFO'))
    commands = [runner_config['shell_path']] + commands
    
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

        if result.stderr:
            raise Exception(result.stderr)

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