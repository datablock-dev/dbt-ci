"""
Retry a failed `run` step with `dbt retry` (--retries).

`dbt retry` reruns the nodes that errored, failed or were skipped in the last
invocation, which it reads from run_results.json. It takes the selection, target,
state and defer setting from that invocation, so it needs only the paths to the
project and profiles.
"""

import logging
import os
from argparse import Namespace
from pathlib import Path
from typing import cast

from dbt_ci.runners import resolve_dbt_commands
from dbt_ci.runners.docker import get_container_paths, parse_docker_env
from dbt_ci.schema import RunnerConfig
from dbt_ci.utilities.run_times import run_results_path

logger = logging.getLogger(__name__)


def get_retries(args: Namespace) -> int:
    """Return how many times a failed step is retried with `dbt retry`, 0 for never."""
    retries = getattr(args, "retries", None)
    if retries is None:
        return 0
    if retries < 0:
        logger.warning(f"Ignoring negative --retries ({retries}); failed steps are not retried.")
        return 0
    return retries


def run_results_marker(args: Namespace) -> int | None:
    """
    Return the modification time of run_results.json, or None if there is none.

    Comparing it before and after a step tells whether the step's dbt command wrote
    its own results, which `dbt retry` needs. A command that fails before running any
    node, on a parse error for example, leaves the previous step's file in place.
    """
    project_dir = getattr(args, "dbt_project_dir", None) or "."
    try:
        return run_results_path(project_dir).stat().st_mtime_ns
    except OSError:
        return None


def resolve_retry_command(args: Namespace) -> list[str]:
    """
    Return the `dbt retry` command for the step that just failed.

    The reference state dbt-ci passes other commands is left out: when dbt retry is
    given --state, it reads run_results.json from there rather than the target path.
    Defer is left out too, since dbt retry takes it from the failed invocation.
    """
    retry_args = Namespace(**{**vars(args), "reference_state": None, "comparison_state": None})
    command = resolve_dbt_commands(["retry"], retry_args, ignore_keys=["defer"])
    return command + retry_state_flag(args)


def retry_state_flag(args: Namespace) -> list[str]:
    """
    Return `--state <target path>` when a DBT_STATE variable would redirect dbt retry.

    dbt reads DBT_STATE as --state, and dbt-ci documents the same variable for its own
    reference state. dbt retry would then look for run_results.json in the reference
    state, so it is pointed back at the target path. dbt retry still takes the state
    the step deferred to from the failed invocation.
    """
    runner_config = cast(RunnerConfig, vars(args))
    if getattr(args, "runner", None) == "docker":
        docker_env = parse_docker_env(runner_config)
        if "DBT_STATE" not in docker_env:
            return []
        project_dir = get_container_paths(runner_config).get("dbt_project_dir")
        if not project_dir:
            logger.debug("DBT_STATE is set in the container, but its project path is unknown.")
            return []
        container_target = docker_env.get("DBT_TARGET_PATH") or "target"
        return ["--state", str(Path(project_dir) / container_target)]
    if not os.environ.get("DBT_STATE"):
        return []
    project_dir = getattr(args, "dbt_project_dir", None) or "."
    return ["--state", str(run_results_path(project_dir).parent.absolute())]
