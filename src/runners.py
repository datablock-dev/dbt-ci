import subprocess
from subprocess import CompletedProcess
from typing import List

def local_runner(commands: List[str], dry_run: bool = False) -> CompletedProcess | None:
    # Build the dbt command based on the provided arguments
    # Execute the dbt command
    print(f"Running command: {' '.join(commands)}")
    
    if dry_run:
        print("DRY RUN: Command would be executed")
        return None
    
    try:
        result = subprocess.run(
            commands, 
            check=True, 
            capture_output=True, 
            text=True
        )

        print(result.stdout)

        return result
    except subprocess.CalledProcessError as e:
        if e.stderr:
            print(f"STDERR: {e.stderr}")
        if e.stdout:
            print(f"STDOUT: {e.stdout}")
        raise

def docker_runner(args):
    # Placeholder for Docker runner implementation
    print("Docker runner is not yet implemented.")