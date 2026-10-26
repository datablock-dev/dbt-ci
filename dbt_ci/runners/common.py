"""Helpers shared by the runners that execute dbt on the host."""

import logging
import os
import subprocess
from subprocess import CompletedProcess
from dbt_ci.errors import ConfigurationError, DbtCommandError

logger = logging.getLogger(__name__)

# dbt flags whose value is a path, made absolute so dbt resolves them the same way
# whatever directory it runs from
PATH_FLAGS = {"--state", "--project-dir", "--profiles-dir", "--target-path", "--log-path"}


def absolutize_path_flags(command: list[str]) -> list[str]:
    """Return the command with the value of every path flag made absolute."""
    absolute_command: list[str] = []
    prev_arg = None
    for arg in command:
        if prev_arg in PATH_FLAGS and not os.path.isabs(arg):
            absolute_command.append(os.path.abspath(arg))
        else:
            absolute_command.append(arg)
        prev_arg = arg
    return absolute_command


def run_dbt_process(argv: list[str], dbt_args: list[str], quiet: bool = False) -> CompletedProcess:
    """
    Run a dbt process, log its output, and raise DbtCommandError if it fails.

    `dbt_args` are the dbt arguments without the executable or shell wrapper, so the
    error names the dbt subcommand rather than the binary that ran it.
    """
    try:
        result = subprocess.run(argv, check=True, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise ConfigurationError(f"Could not run '{argv[0]}': {e.strerror}.") from e
    except subprocess.CalledProcessError as e:
        if e.stderr:
            logger.error(e.stderr)
        if e.stdout:
            logger.error(e.stdout)
        raise DbtCommandError(
            dbt_args, returncode=e.returncode, stdout=e.stdout or "", stderr=e.stderr or ""
        ) from e

    if not quiet:
        logger.info(result.stdout)

    # dbt writes warnings and its own log lines to stderr on successful runs, so only the
    # exit code (enforced by check=True above) decides success or failure.
    if result.stderr:
        logger.warning(result.stderr)

    return result
