"""The bash runner: runs dbt through a shell, or through a wrapper script given as --shell-path."""

import os
import shlex
import logging
from subprocess import CompletedProcess
from dbt_ci.runners.common import run_dbt_process
from dbt_ci.utilities.logging import setup_logging
from dbt_ci.schema import RunnerConfig

logger = logging.getLogger(__name__)

# Shells that need the dbt entrypoint passed through `-c` rather than dbt's arguments
SHELL_INTERPRETERS = {"bash", "sh", "zsh", "dash", "ksh"}


def bash_runner(commands: list[str], runner_config: RunnerConfig) -> CompletedProcess | None:
    """
    Execute dbt commands using a custom dbt binary/script.

    Args:
        commands: The dbt command and arguments to run (e.g., ['dbt', 'ls', '--select', ...])
        shell_path: Path to the custom dbt executable to use (e.g., 'bin/dbt', '/usr/local/bin/dbt')
        dry_run: If True, only print the command
        quiet: If True, suppress stdout

    Note: if shell_path is a plain shell (e.g. /bin/bash), the entrypoint is run through
    it with `-c`; otherwise shell_path is treated as a dbt wrapper script.
    """
    setup_logging(runner_config.get("log_level", "INFO"))
    shell_path = runner_config["shell_path"]
    if os.path.basename(shell_path) in SHELL_INTERPRETERS:
        # A plain shell (the default /bin/bash) cannot take dbt arguments itself, so it
        # runs the entrypoint instead. A wrapper script receives the dbt arguments directly.
        entrypoint = runner_config.get("entrypoint") or "dbt"
        argv = [shell_path, "-c", shlex.join([entrypoint, *commands])]
    else:
        argv = [shell_path, *commands]

    if not runner_config.get("quiet", False):
        logger.debug(f"Running command: {' '.join(argv)}")

    if runner_config.get("dry_run", False):
        logger.info("DRY RUN: Command would be executed")
        return None

    return run_dbt_process(argv, commands, quiet=runner_config.get("quiet", False))
