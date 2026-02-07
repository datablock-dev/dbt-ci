from dbt.cli.main import dbtRunner, CatalogArtifact, Manifest, RunExecutionResult
from subprocess import CompletedProcess
from typing import List

def dbt_runner(
    commands: List[str], 
    dry_run: bool = False,
    quiet: bool = False
) -> bool | CatalogArtifact | List[str] | Manifest | RunExecutionResult | None:
    """Execute dbt commands through dbtRunner."""
    runner = dbtRunner()

    if not quiet:
        print(f"Running command: {' '.join(commands)}")
    
    if dry_run:
        print("DRY RUN: Command would be executed")
        return None
    
    try:
        result = runner.invoke(args=commands)

        if not quiet:
            print(result.result)

        return result.result
    except BaseException as e:
        print(e)
        raise