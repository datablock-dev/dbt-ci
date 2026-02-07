import subprocess
from subprocess import CompletedProcess
from typing import List

def local_runner(
    commands: List[str], 
    dry_run: bool = False,
    quiet: bool = False
) -> CompletedProcess | None:
    """Execute dbt commands locally."""
    if not quiet:
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

        if not quiet:
            print(result.stdout)

        return result
    except subprocess.CalledProcessError as e:
        if e.stderr:
            print(e.stderr)
        if e.stdout:
            print(e.stdout)
        raise