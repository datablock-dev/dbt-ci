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
from dbt_ci.notifications.github import post_pr_comment
from dbt_ci.graph.graph_utils import (
    get_display_name,
    get_downstream_dependencies,
    get_node_ids_from_structured_nodes,
)
from dbt_ci.schema import DependencyGraph, StateChangeSummary, StateChangeSummaryKeys
from dbt_ci.utilities.cache import CacheManager
from dbt_ci.utilities.logging import print_exception
from dbt_ci.utilities.run_times import RUN_TIMES_FILE, format_seconds

logger = logging.getLogger(__name__)

CHANGE_TYPES: dict[StateChangeSummaryKeys, str] = {
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
        pr_comment = getattr(args, "pr_comment", False)
        # The comment is always markdown, whatever --format the written report uses
        markdown = (
            render_markdown(cache_dict, run_report, args)
            if output_format != "json" or pr_comment
            else ""
        )
        if output_format == "json":
            rendered = json.dumps(
                {
                    "report": run_report,
                    "changes": cache_dict,
                    "run_times": cache.get_cache(RUN_TIMES_FILE),
                },
                indent=2,
                default=lambda o: list(o) if isinstance(o, set) else str(o),
            )
        else:
            rendered = markdown

        write_report(rendered, args)

        if pr_comment:
            post_pr_comment(markdown)
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
    lines.extend(render_baseline(cache_dict))
    lines.extend(render_change_summary(cache_dict))
    lines.extend(render_exposure_impact(cache_dict, args))
    lines.extend(render_run_time(args))
    lines.extend(render_command_status(run_report))
    return "\n".join(lines).rstrip() + "\n"


def render_baseline(cache_dict: StateChangeSummary | None) -> list[str]:
    """Say which manifest the change set was compared against, when it was the merge base."""
    # The cache holds init's config block next to the change set
    cache = cast(dict[str, Any], cache_dict or {})
    baseline = (cache.get("config") or {}).get("baseline") or {}
    description = baseline.get("description")
    return [f"Compared against {description}.", ""] if description else []


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

    # Why each node is in the change set, recorded by init; older caches have none
    reasons: dict[str, list[str]] = cache_dict.get("reasons") or {}  # type: ignore[assignment]
    for change_key, label in CHANGE_TYPES.items():
        structured = cache_dict.get(change_key) or {}
        if not structured:
            continue
        entries: list[str] = []
        for resource_type, nodes in sorted(structured.items()):
            for node_id, node in nodes.items():
                entry = f"- `{node.get('name', '?')}` ({resource_type})"
                why = "; ".join(reasons.get(node_id, []))
                entries.append(f"{entry}: {why}" if why else entry)
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
    change_groups: tuple[tuple[tuple[StateChangeSummaryKeys, ...], bool], ...] = (
        (("modified_nodes", "new_nodes"), False),
        (("deleted_nodes",), True),
    )
    for change_keys, is_reference in change_groups:
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


def render_run_time(args: Namespace) -> list[str]:
    """
    Compare the dbt run time this run spent with the recorded time of what it left out.

    The recorded times come from earlier deploys (see dbt_ci.utilities.run_times); nodes
    no longer in the project are not counted. Without them only this run's time is shown.
    """
    run_times = CacheManager(args).get_cache(RUN_TIMES_FILE) or {}
    this_run: dict[str, float] = run_times.get("this_run") or {}
    if not this_run:
        return []
    spent = sum(this_run.values())
    lines = [
        "### Run time",
        "",
        f"Built **{len(this_run)}** node(s) in **{format_seconds(spent)}** of dbt run time.",
    ]

    recorded: dict[str, float] = run_times.get("recorded") or {}
    graph = load_graph(args)
    in_project = _node_ids(graph) if graph is not None else None
    left_out = [
        seconds
        for node_id, seconds in recorded.items()
        if node_id not in this_run and (in_project is None or node_id in in_project)
    ]
    if left_out:
        skipped = sum(left_out)
        share = round(100 * skipped / (skipped + spent)) if skipped + spent else 0
        lines.append(
            f"The **{len(left_out)}** other node(s) with a recorded run time took about "
            f"**{format_seconds(skipped)}** when they last ran, so this run skipped about "
            f"**{share}%** of the run time of a full build."
        )
    else:
        lines.append(
            "Publish run times with `dbt-ci finalize` on deploys to see what the rest of the "
            "project would have taken."
        )
    lines.extend(
        [
            "",
            "<sub>Run time is the sum of each node's execution time as dbt reports it, not "
            "wall-clock time: it is what the warehouse spent working.</sub>",
            "",
        ]
    )
    return lines


def _node_ids(graph: DependencyGraph) -> set[str]:
    """Return every node id in a dependency graph."""
    ids: set[str] = set()
    for nodes in graph.values():
        if isinstance(nodes, dict):
            ids.update(nodes)
    return ids


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
        lines.append(f"| `{command}` | {status_icon(status)} {status} | {format_duration(entry)} |")
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
