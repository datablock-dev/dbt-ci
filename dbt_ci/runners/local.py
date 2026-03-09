"""Local runner implementation for executing dbt commands directly on the host machine."""
import os
import sys
import subprocess
import logging
from subprocess import CompletedProcess
from typing import List
from dbt_ci.logging import setup_logging
from dbt_ci.schema import RunnerConfig

logger = logging.getLogger(__name__)

def local_runner(commands: list[str], runner_config: RunnerConfig) -> CompletedProcess | None:
    """Execute dbt commands locally."""
    setup_logging(runner_config.get('log_level', 'INFO'))
    full_command = [*([runner_config.get('entrypoint')] if runner_config.get('entrypoint') else []), *commands]
    absolute_command = []
    path_flags = {'--state', '--project-dir', '--profiles-dir', '--target-path', '--log-path'}
    prev_arg = None
        
    for arg in full_command:
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
        result = subprocess.run(
            absolute_command,
            check=True,
            capture_output=True,
            text=True
        )

        if not runner_config.get('quiet', False):
            logger.info(result.stdout)
        
        if result.stderr:
            raise Exception(result.stderr)

        return result
    except subprocess.CalledProcessError as e:
        if e.stderr:
            logger.error(e.stderr)
        if e.stdout:
            logger.error(e.stdout)
        raise
    except Exception as e:
        logger.error(e)
        sys.exit(1)