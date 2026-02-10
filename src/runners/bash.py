import sys
from typing import List
import subprocess
from subprocess import CompletedProcess
from src.schema import RunnerConfig

def bash_runner(
    commands: List[str],
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
    # Replace 'dbt' command with custom path
    commands = [runner_config['shell_path']] + commands
    
    if not runner_config.get('quiet', False):
        print(f"Running command: {' '.join(commands)}")
    
    if runner_config.get('dry_run', False):
        print("DRY RUN: Command would be executed")
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
            print(e.stderr)
        if e.stdout:
            print(e.stdout)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)