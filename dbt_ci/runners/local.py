"""Local runner implementation for executing dbt commands directly on the host machine."""

import logging
from subprocess import CompletedProcess
from dbt_ci.runners.common import absolutize_path_flags, run_dbt_process
from dbt_ci.utilities.logging import setup_logging
from dbt_ci.schema import RunnerConfig

logger = logging.getLogger(__name__)


def local_runner(commands: list[str], runner_config: RunnerConfig) -> CompletedProcess | None:
    """Execute dbt commands locally, raising DbtCommandError if dbt fails."""
    setup_logging(runner_config.get("log_level", "INFO"))
    entrypoint = runner_config.get("entrypoint")
    absolute_command = absolutize_path_flags([*([entrypoint] if entrypoint else []), *commands])

    if not runner_config.get("quiet", False):
        logger.debug(f"Running command: {' '.join(absolute_command)}")

    if runner_config.get("dry_run", False):
        logger.info("DRY RUN: Command would be executed")
        return None

    return run_dbt_process(absolute_command, commands, quiet=runner_config.get("quiet", False))
