import subprocess
from subprocess import CompletedProcess
from typing import List
from src.schema import RunnerConfig

def local_runner(
    commands: List[str],
    runner_config: RunnerConfig
) -> CompletedProcess | None:
    """Execute dbt commands locally."""
    if not runner_config.get('quiet', False):
        print(f"Running command: {' '.join(commands)}")
    
    if runner_config.get('dry_run', False):
        print("DRY RUN: Command would be executed")
        return None
    
    try:
        result = subprocess.run(
            commands,
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