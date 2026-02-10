from subprocess import CompletedProcess
import sys
from typing import List
from dbt.cli.main import dbtRunner

from src.schema import RunnerConfig

def dbt_runner(
    commands: List[str],
    runner_config: RunnerConfig
) -> CompletedProcess | None:
    """Execute dbt commands through dbtRunner (Python API).
    
    Returns a CompletedProcess-compatible object for consistency with other runners.
    """
    runner = dbtRunner()

    if not runner_config.get('quiet', False):
        print(f"Running command: {' '.join(commands)}")
    
    if runner_config.get('dry_run', False):
        print("DRY RUN: Command would be executed")
        return None
    
    try:
        result = runner.invoke(args=commands)

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
        print(e)
        raise
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)

