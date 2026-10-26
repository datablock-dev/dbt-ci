"""Run the dbt-ci commands listed in the action's `commands` input."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List, Mapping, Optional

from dbt_ci_action import workflow
from dbt_ci_action.changes import write_change_outputs
from dbt_ci_action.commands import Step, parse_commands
from dbt_ci_action.inputs import Inputs, common_flags, flags_for, load_inputs


def build_env(inputs: Inputs, base: Mapping[str, str]) -> Dict[str, str]:
    """
    Return the environment dbt-ci runs with.

    The cache directory is pinned under RUNNER_TEMP, which the runner empties for every
    job, so concurrent jobs on a self-hosted runner never share a cache. It is exported to
    the job so later steps that call dbt-ci themselves (e.g. `ephemeral destroy` in an
    `if: always()` step) find the cache `init` wrote.
    """
    env = dict(base)
    if not env.get("DBT_CI_CACHE_DIR"):
        root = env.get("RUNNER_TEMP") or tempfile.gettempdir()
        env["DBT_CI_CACHE_DIR"] = os.path.join(root, "dbt-ci")
    workflow.export_env("DBT_CI_CACHE_DIR", env["DBT_CI_CACHE_DIR"])

    if inputs.get("github-token"):
        env["GITHUB_TOKEN"] = inputs["github-token"]
    if inputs.get("slack-webhook"):
        env["DBT_NOTIFICATIONS_WEBHOOK"] = inputs["slack-webhook"]
    return env


def warn_if_shallow(steps: List[Step], inputs: Inputs) -> None:
    """Warn when a git-based comparison is about to run in a shallow checkout."""
    if not any(step.command == ("init",) for step in steps):
        return
    if inputs.get("comparison-strategy") == "dbt":
        return
    result = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"], capture_output=True, text=True
    )
    if result.stdout.strip() == "true":
        workflow.warning(
            "This checkout is shallow, so the git comparison may not find the merge base "
            "with the base branch and can report changes made on the base branch as part "
            "of this one. Check out with 'fetch-depth: 0', or set comparison-strategy: dbt."
        )


def run_steps(
    executable: str, steps: List[Step], inputs: Inputs, env: Mapping[str, str]
) -> Optional[Step]:
    """
    Run the steps in order and return the first one that failed, if any.

    After a failure only the steps marked always_run (report, ephemeral destroy) still
    run, so the report explains the failure and the ephemeral environment is torn down.
    """
    failed: Optional[Step] = None
    for step in steps:
        if failed and not step.always_run:
            print(f"Skipping 'dbt-ci {step.label}' because 'dbt-ci {failed.label}' failed.")
            continue

        argv = [executable, *step.command, *flags_for(step.command, inputs), *step.args]
        with workflow.group(f"dbt-ci {step.label}"):
            returncode = subprocess.run(argv, env=dict(env)).returncode

        if returncode != 0:
            workflow.error(f"'dbt-ci {step.label}' failed with exit code {returncode}.")
            failed = failed or step
    return failed


def main() -> int:
    """Run the action and return its exit code."""
    try:
        inputs = load_inputs(os.environ.get("DBT_CI_ACTION_INPUTS"))
        steps = parse_commands(inputs.get("commands", ""))
        flags_for(("report",), inputs)  # validates the boolean inputs before anything runs
    except ValueError as e:
        workflow.error(str(e))
        return 2

    executable = os.environ.get("DBT_CI_EXECUTABLE") or shutil.which("dbt-ci")
    if not executable:
        workflow.error(
            "dbt-ci is not installed. Leave 'install' enabled, or install it in an earlier step."
        )
        return 2

    env = build_env(inputs, os.environ)
    warn_if_shallow(steps, inputs)
    failed = run_steps(executable, steps, inputs, env)

    report_path = os.path.join(
        env.get("RUNNER_TEMP") or tempfile.gettempdir(), "dbt-ci-report.json"
    )
    write_change_outputs(executable, common_flags(inputs), env, report_path)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
