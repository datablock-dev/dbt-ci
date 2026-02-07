from typing import List, Dict
import subprocess
from subprocess import CompletedProcess

def bash_runner(
    commands: List[str],
    shell_path: str,
    dry_run: bool = False,
    quiet: bool = False
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
    # Replace 'dbt' command with custom path
    if commands[0] == 'dbt':
        commands = [shell_path] + commands[1:]
    
    if not quiet:
        print(f"Running command: {' '.join(commands)}")
    
    if dry_run:
        print("DRY RUN: Command would be executed")
        return None
    
    try:
        result = subprocess.run(
            args=commands,
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
    