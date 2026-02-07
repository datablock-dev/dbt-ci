from typing import List, Dict
import subprocess
from subprocess import CompletedProcess

def bash_runner(
    commands: List[str],
    shell_path: str,
    dry_run: bool = False,
    quiet: bool = False
):
    """
        Execute dbt commands using a specified bash file
        Args:
            commands: The dbt command and arguments to run
            shell_path: Path to the shell executable to use (e.g., /bin/bash)
            dry_run: If True, only print the command
            quiet: If True, suppress stdout
        
    """
    if dry_run:
        print("DRY RUN: Command would be executed")
        return None
    
    try:
        result = subprocess.run(
            args=[shell_path, "-c", " ".join(commands)],
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
    