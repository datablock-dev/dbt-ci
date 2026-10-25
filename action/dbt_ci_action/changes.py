"""Expose the change set detected by `init` as step outputs."""
from __future__ import annotations

import json
import os
import subprocess
from typing import Dict, List, Mapping, Optional

from dbt_ci_action import workflow

CHANGE_OUTPUTS: Dict[str, str] = {
    "modified_nodes": "modified",
    "new_nodes": "new",
    "deleted_nodes": "deleted",
}


def count_changes(report: Mapping) -> Dict[str, int]:
    """Count the modified, new and deleted nodes in a `dbt-ci report --format json` payload."""
    changes = report.get("changes") or {}
    return {
        output: sum(len(nodes) for nodes in (changes.get(key) or {}).values())
        for key, output in CHANGE_OUTPUTS.items()
    }


def write_change_outputs(
    executable: str,
    flags: List[str],
    env: Mapping[str, str],
    report_path: str,
) -> Optional[Dict[str, int]]:
    """
    Render the JSON report and set the change-count outputs from it.

    Goes through `dbt-ci report` rather than reading the cache files, which are internal
    to dbt-ci. The PR comment is switched off so this extra render never posts one. When
    there is no cache yet (init did not run or failed), no outputs are set.
    """
    # A report left by an earlier invocation in the same job must not pass for this one.
    if os.path.exists(report_path):
        os.remove(report_path)

    result = subprocess.run(
        [executable, "report", "--format", "json", "--output", report_path, "--no-pr-comment", *flags],
        env=dict(env),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not os.path.exists(report_path):
        print(f"::debug::No change set to expose as outputs: {result.stderr.strip()}")
        return None

    with open(report_path, encoding="utf-8") as f:
        counts = count_changes(json.load(f))

    for name, count in counts.items():
        workflow.set_output(name, str(count))
    workflow.set_output("has-changes", "true" if any(counts.values()) else "false")
    workflow.set_output("report-json", report_path)
    return counts
