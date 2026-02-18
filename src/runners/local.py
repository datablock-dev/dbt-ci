"""Local runner implementation for executing dbt commands directly on the host machine."""
import os
import sys
import subprocess
import logging
from subprocess import CompletedProcess
from argparse import Namespace
from typing import List
from src.logging import setup_logging

logger = logging.getLogger(__name__)

def local_runner(commands: List[str], args: Namespace) -> CompletedProcess | None:
    """Execute dbt commands locally."""
    setup_logging(getattr(args, 'log_level', 'INFO'))
    full_command = [*([getattr(args, 'entrypoint')] if getattr(args, 'entrypoint') else []), *commands]
    absolute_command = []
    path_flags = {'--state', '--project-dir', '--profiles-dir', '--target-path', '--log-path'}
    prev_arg = None
        
    for arg in full_command:
        if prev_arg in path_flags and isinstance(arg, str):
            absolute_command.append(os.path.abspath(arg) if not os.path.isabs(arg) else arg)
        else:
            absolute_command.append(arg)
        prev_arg = arg

    if not getattr(args, 'quiet', False):
        logger.debug(f"Running command: {' '.join(absolute_command)}")
    
    if getattr(args, 'dry_run', False):
        logger.info("DRY RUN: Command would be executed")
        return None
    
    try:
        result = subprocess.run(
            absolute_command,
            check=True,
            capture_output=True,
            text=True
        )

        if not getattr(args, 'quiet', False):
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