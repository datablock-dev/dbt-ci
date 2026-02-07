from dbt.cli.main import dbtRunner, CatalogArtifact, Manifest, RunExecutionResult
from subprocess import CompletedProcess
from typing import List

def dbt_runner(
    commands: List[str], 
    dry_run: bool = False,
    quiet: bool = False
) -> CompletedProcess | None:
    """Execute dbt commands through dbtRunner (Python API).
    
    Returns a CompletedProcess-compatible object for consistency with other runners.
    """
    runner = dbtRunner()

    if not quiet:
        print(f"Running command: {' '.join(commands)}")
    
    if dry_run:
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
        
        if not quiet:
            print(stdout)
        
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