import logging
from subprocess import CompletedProcess
from dbt.cli.main import dbtRunner
from dbt_ci.errors import DbtCommandError
from dbt_ci.runners.common import absolutize_path_flags
from dbt_ci.utilities.logging import setup_logging
from dbt_ci.schema import RunnerConfig

logger = logging.getLogger(__name__)


def dbt_runner(commands: list[str], runner_config: RunnerConfig) -> CompletedProcess | None:
    """Execute dbt commands through dbtRunner (Python API).

    Returns a CompletedProcess-compatible object for consistency with other runners, and
    raises DbtCommandError when dbt fails, like they do.
    """
    setup_logging(runner_config.get("log_level", "INFO"))
    runner = dbtRunner()
    # dbtRunner Python API expects commands without 'dbt' prefix (e.g., ['compile', '--target', 'prod'])
    # If first element is 'dbt', strip it; otherwise use commands as-is
    dbt_command_args = commands[1:] if commands and commands[0] == "dbt" else commands
    absolute_command = absolutize_path_flags(dbt_command_args)

    if not runner_config.get("quiet", False):
        logger.debug(f"Running command: {' '.join(absolute_command)}")

    if runner_config.get("dry_run", False):
        logger.info("DRY RUN: Command would be executed")
        return None

    result = runner.invoke(args=absolute_command)

    # Convert dbt result to stdout string format
    # For 'ls' command, result.result is a list of node names
    if isinstance(result.result, list):
        stdout = "\n".join(result.result)
    elif isinstance(result.result, str):
        stdout = result.result
    else:
        stdout = str(result.result) if result.result is not None else ""

    # dbt raises for errors that stop it from running at all (a bad flag, a project that
    # does not parse) and reports failed nodes through `success` instead.
    if result.exception is not None:
        raise DbtCommandError(
            dbt_command_args, stdout=stdout, detail=str(result.exception)
        ) from result.exception
    if not result.success:
        raise DbtCommandError(dbt_command_args, returncode=1, stdout=stdout)

    return CompletedProcess(args=commands, returncode=0, stdout=stdout, stderr="")
