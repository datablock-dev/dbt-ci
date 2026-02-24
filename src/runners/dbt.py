import os
import sys
import logging
from subprocess import CompletedProcess
from typing import List
from dbt.cli.main import dbtRunner
from src.logging import setup_logging
from src.schema import RunnerConfig

logger = logging.getLogger(__name__)

def dbt_runner(
    commands: list[str],
    runner_config: RunnerConfig
) -> CompletedProcess | None:
    """Execute dbt commands through dbtRunner (Python API).
    
    Returns a CompletedProcess-compatible object for consistency with other runners.
    """
    setup_logging(runner_config.get('log_level', 'INFO'))
    runner = dbtRunner()
    # dbtRunner Python API expects commands without 'dbt' prefix (e.g., ['compile', '--target', 'prod'])
    # If first element is 'dbt', strip it; otherwise use commands as-is
    dbt_command_args = commands[1:] if commands and commands[0] == 'dbt' else commands
        
    # Convert paths to absolute for reliability
    absolute_command = []
    path_flags = {'--state', '--project-dir', '--profiles-dir', '--target-path', '--log-path'}
    prev_arg = None
    
    for arg in dbt_command_args:
        if prev_arg in path_flags and isinstance(arg, str):
            absolute_command.append(os.path.abspath(arg) if not os.path.isabs(arg) else arg)
        else:
            absolute_command.append(arg)
        prev_arg = arg

    if not runner_config.get('quiet', False):
        logger.debug(f"Running command: {' '.join(absolute_command)}")
    
    if runner_config.get('dry_run', False):
        logger.info("DRY RUN: Command would be executed")
        return None
    
    try:
        result = runner.invoke(args=absolute_command)

        # Convert dbt result to stdout string format
        # For 'ls' command, result.result is a list of node names
        if isinstance(result.result, list):
            stdout = "\n".join(result.result)
        elif isinstance(result.result, str):
            stdout = result.result
        else:
            stdout = str(result.result) if result.result is not None else ""
        
        if result.exception is not None:
            raise result.exception

        # Return CompletedProcess for compatibility with other runners
        return CompletedProcess(
            args=commands,
            returncode=0 if result.success else 1,
            stdout=stdout,
            stderr=""
        )
    except BaseException as e:
        logger.error(e)
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)

