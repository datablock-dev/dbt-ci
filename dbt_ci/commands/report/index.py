"""Render the run report that init/run/delete/ephemeral/migration already record.

Every command writes its status, timings and resolved variables into report.json, and
the change set into cache.json, but nothing ever read them back - the files were written
and then deleted by finalize. This turns them into something a reviewer sees.
"""
import json
import logging
import os
import sys
from argparse import Namespace
from datetime import datetime
from typing import Any, cast

import click

from dbt_ci.graph.dependency_graph import DbtGraph
from dbt_ci.graph.graph_utils import (
    get_display_name,
    get_downstream_dependencies,
    get_node_ids_from_structured_nodes,
)
from dbt_ci.schema import DependencyGraph, StateChangeSummary
from dbt_ci.utilities.cache import CacheManager
from dbt_ci.utilities.logging import print_exception

logger = logging.getLogger(__name__)

CHANGE_TYPES: dict[str, str] = {
    "modified_nodes": "Modified",
    "new_nodes": "New",
    "deleted_nodes": "Deleted",
}

# Beyond this many nodes of one kind, the list is collapsed behind a <details> element so
# the summary stays readable on a large change set.
COLLAPSE_THRESHOLD = 10


def report(args: Namespace) -> None:
    """Render the cached run report and write it to the requested destination."""
    try:
        cache = CacheManager(args)
        cache_dict = cast(StateChangeSummary | None, cache.get_cache())
        run_report = cast(dict[str, Any] | None, cache.get_cache("report.json"))

        if cache_dict is None and run_report is None:
            logger.error(
                "No cache found, please run 'dbt-ci init' first to generate the state and "
                "run report this command renders."
            )
            sys.exit(1)

        output_format = getattr(args, "format", "markdown")
        if output_format == "json":
            rendered = json.dumps(
                {"report": run_report, "changes": cache_dict},
                indent=2,
                default=lambda o: list(o) if isinstance(o, set) else str(o),
            )
        else:
            rendered = render_markdown(cache_dict, run_report, args)

        write_report(rendered, args)
    except Exception as e:
        print_exception(e, "Error generating report")
        sys.exit(1)


def write_report(rendered: str, args: Namespace) -> None:
    """
    Write the rendered report to --output, GITHUB_STEP_SUMMARY, or stdout.

    Appending to GITHUB_STEP_SUMMARY by default means the report shows up on the job
    page in GitHub Actions without the workflow needing to do anything.
    """
    destination = getattr(args, "output", None) or os.environ.get("GITHUB_STEP_SUMMARY")

    if not destination:
        click.echo(rendered)
        return

    # GITHUB_STEP_SUMMARY accumulates across steps, so append rather than truncate.
    mode = "a" if destination == os.environ.get("GITHUB_STEP_SUMMARY") else "w"
    with open(destination, mode, encoding="utf-8") as f:
        f.write(rendered + "\n")
    logger.info(f"Report written to {destination}")


def render_markdown(
    cache_dict: StateChangeSummary | None,
    run_report: dict[str, Any] | None,
    args: Namespace,
) -> str:
    """Render the full report as GitHub-flavoured markdown."""
    lines: list[str] = ["## dbt-ci run report", ""]
    lines.extend(render_change_summary(cache_dict))
    lines.extend(render_exposure_impact(cache_dict, args))
    lines.extend(render_command_status(run_report))
    return "\n".join(lines).rstrip() + "\n"


def render_change_summary(cache_dict: StateChangeSummary | None) -> list[str]:
    """Render the counts and node lists for modified, new and deleted resources."""
    if not cache_dict:
        return ["No state comparison found.", ""]

    counts: dict[str, int] = {}
    for change_key in CHANGE_TYPES:
        structured = cache_dict.get(change_key) or {}
        counts[change_key] = sum(len(nodes) for nodes in structured.values())

    if not any(counts.values()):
        return ["No changes detected against the reference state.", ""]

    lines = ["| Change | Count |", "|---|---:|"]
    for change_key, label in CHANGE_TYPES.items():
        lines.append(f"| {label} | {counts[change_key]} |")
    lines.append("")

    for change_key, label in CHANGE_TYPES.items():
        structured = cache_dict.get(change_key) or {}
        if not structured:
            continue
        entries: list[str] = []
        for resource_type, nodes in sorted(structured.items()):
            for node in nodes.values():
                entries.append(f"- `{node.get('name', '?')}` ({resource_type})")
        lines.extend(collapsible(f"{label} ({len(entries)})", entries))

    return lines


def render_exposure_impact(cache_dict: StateChangeSummary | None, args: Namespace) -> list[str]:
    """
    List exposures downstream of the change set.

    Exposures are what the warehouse is for - dashboards and downstream consumers - so
    naming the ones a pull request touches is the most useful single line in the report.
    """
    if not cache_dict:
        return []

    entries: set[str] = set()

    # Modified and new nodes are resolved against the target graph; deleted nodes only
    # exist in the reference graph, and an exposure downstream of a deleted model is
    # precisely the case worth surfacing.
    for change_keys, is_reference in ((("modified_nodes", "new_nodes"), False), (("deleted_nodes",), True)):
        node_ids: list[str] = []
        for change_key in change_keys:
            node_ids.extend(get_node_ids_from_structured_nodes(cache_dict.get(change_key)) or [])
        if not node_ids:
            continue

        graph = load_graph(args, is_reference=is_reference)
        if graph is None:
            continue

        exposures = get_downstream_dependencies(
            dependency_graph=graph,
            node_ids=node_ids,
            node_type="exposure",
        )
        for exposure_id in exposures or set():
            entries.add(get_display_name(graph, exposure_id))

    if not entries:
        return []

    listed = sorted(f"- `{name}`" for name in entries)
    return [f"### ⚠️ Affects {len(listed)} exposure(s)", "", *listed, ""]


def load_graph(args: Namespace, is_reference: bool = False) -> DependencyGraph | None:
    """Load a dependency graph from cache, returning None when unavailable."""
    try:
        return DbtGraph(args, is_reference=is_reference).to_dict()
    except Exception as e:
        logger.debug(f"Could not load the dependency graph for exposure impact: {e}")
        return None


def render_command_status(run_report: dict[str, Any] | None) -> list[str]:
    """Render each command's status and how long it took."""
    if not run_report:
        return []

    lines = ["### Commands", "", "| Command | Status | Duration |", "|---|---|---:|"]
    for command, entry in run_report.items():
        if not isinstance(entry, dict):
            continue
        status = entry.get("status", "unknown")
        lines.append(
            f"| `{command}` | {status_icon(status)} {status} | {format_duration(entry)} |"
        )
    lines.append("")
    return lines


def status_icon(status: str) -> str:
    """Return an icon for a command status."""
    return {"completed": "✅", "failed": "❌", "started": "⏳"}.get(status, "•")


def format_duration(entry: dict[str, Any]) -> str:
    """
    Return how long a command took, based on the timestamps it recorded.

    The end key is named after the terminal status (completed_at, failed_at), so it is
    looked up from the status rather than assumed.
    """
    status = entry.get("status")
    end_key = f"{status}_at"
    if not status or end_key == "started_at":
        # Still running: the status has no end timestamp of its own, and reusing
        # started_at would report a duration of zero.
        return "-"

    started_at = entry.get("started_at")
    finished_at = entry.get(end_key)
    if not started_at or not finished_at:
        return "-"

    try:
        delta = datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at)
    except (TypeError, ValueError):
        return "-"

    seconds = delta.total_seconds()
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{int(seconds // 60)}m {int(seconds % 60)}s"


def collapsible(summary: str, entries: list[str]) -> list[str]:
    """Return entries inline, or folded into a <details> block when there are many."""
    if not entries:
        return []
    if len(entries) <= COLLAPSE_THRESHOLD:
        return [f"**{summary}**", "", *entries, ""]
    return [
        "<details>",
        f"<summary>{summary}</summary>",
        "",
        *entries,
        "",
        "</details>",
        "",
    ]
