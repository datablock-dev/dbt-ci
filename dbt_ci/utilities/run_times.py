"""
Record how long dbt spent on each node, so the report can show what a run skipped.

After each dbt command, `run` reads dbt's run_results.json and keeps every node's
execution time in the cache. `finalize` merges them into `run_times.json` next to the
published manifest, and the next `init` downloads that file with the state. The report
then compares the time this run spent with the recorded time of the nodes it left out.

The times are the sum of each node's execution time as dbt reports it, not wall-clock
time: with several threads a build finishes sooner, but the warehouse still does the
work, so the sum tracks cost.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dbt_ci.schema import StorageConnectorConfig

logger = logging.getLogger(__name__)

RUN_TIMES_FILE = "run_times.json"
# Results dbt reports for nodes it did not execute
NOT_EXECUTED = {"skipped"}
# Tolerated difference between the clock that started a command and dbt's timestamp
CLOCK_SKEW_SECONDS = 2


def run_results_path(dbt_project_dir: str) -> Path:
    """Return where dbt writes run_results.json for the project."""
    target_path = os.environ.get("DBT_TARGET_PATH") or "target"
    return Path(dbt_project_dir) / target_path / "run_results.json"


def read_node_times(dbt_project_dir: str, since: datetime) -> dict[str, float]:
    """
    Return the execution time of each node in run_results.json written after `since`.

    A file written before the command started belongs to an earlier command (dbt did
    not get far enough to write its own), so it is ignored.
    """
    path = run_results_path(dbt_project_dir)
    try:
        results = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.debug(f"No run times recorded: could not read {path}: {e}")
        return {}
    generated = _parse_time((results.get("metadata") or {}).get("generated_at"))
    if generated is None or (since - generated).total_seconds() > CLOCK_SKEW_SECONDS:
        logger.debug(f"No run times recorded: {path} predates this command.")
        return {}
    times: dict[str, float] = {}
    for result in results.get("results") or []:
        node_id = result.get("unique_id")
        seconds = result.get("execution_time")
        if not isinstance(node_id, str) or not isinstance(seconds, (int, float)):
            continue
        if str(result.get("status", "")).lower() in NOT_EXECUTED or seconds <= 0:
            continue
        times[node_id] = round(float(seconds), 3)
    return times


def merge_times(published: dict[str, Any] | None, new: dict[str, float]) -> dict[str, Any]:
    """Return the published run times updated with this run's, keeping nodes it didn't run."""
    nodes = dict((published or {}).get("nodes") or {})
    nodes.update(new)
    return {
        "nodes": nodes,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def sibling_uri(state_uri: str, file_name: str) -> str:
    """Return the URI of a file next to the state, as finalize uploads it."""
    directory = state_uri.rsplit("/", 1)[0] if state_uri.endswith(".json") else state_uri
    return f"{directory.rstrip('/')}/{file_name}"


def download_run_times(uri: str, connector: StorageConnectorConfig) -> dict[str, float]:
    """Return the node times stored at a URI, or {} when there are none yet."""
    try:
        if uri not in connector["list"](uri):
            return {}
        stored = connector["download"](uri)
    except Exception as e:
        logger.warning(f"Could not read run times from {uri}: {e}")
        return {}
    return node_times(stored)


def read_local_run_times(state_dir: str) -> dict[str, float]:
    """Return the node times kept in a local state directory, or {} when there are none."""
    path = Path(state_dir) / RUN_TIMES_FILE
    try:
        return node_times(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}


def node_times(stored: Any) -> dict[str, float]:
    """Return the valid node times from a run_times.json document."""
    nodes = stored.get("nodes") if isinstance(stored, dict) else None
    if not isinstance(nodes, dict):
        return {}
    return {
        node_id: float(seconds)
        for node_id, seconds in nodes.items()
        if isinstance(node_id, str) and isinstance(seconds, (int, float)) and seconds > 0
    }


def format_seconds(seconds: float) -> str:
    """Format a duration for the report, e.g. 0.4s, 45s, 3m 05s or 1h 02m."""
    if seconds < 10:
        return f"{seconds:.1f}s"
    total = int(round(seconds))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _parse_time(value: Any) -> datetime | None:
    """Parse dbt's generated_at timestamp as an aware UTC datetime."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
