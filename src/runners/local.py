"""Local runner implementation for executing dbt commands directly on the host machine."""
import os
import sys
import subprocess
from subprocess import CompletedProcess
from typing import List
from src.schema import RunnerConfig

def local_runner(commands: List[str], runner_config: RunnerConfig) -> CompletedProcess | None:
    """Execute dbt commands locally."""
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
        print(f"Running command: {' '.join(absolute_command)}")
    
    if runner_config.get('dry_run', False):
        print("DRY RUN: Command would be executed")
        return None
    
    try:
        result = subprocess.run(
            absolute_command,
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
            print(e.stderr)
        if e.stdout:
            print(e.stdout)
        raise
    except Exception as e:
        print(e)
        sys.exit(1)