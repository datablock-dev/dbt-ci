"""
Review the models a pull request changes with Claude, and record the findings.

`init` must have run first. The findings are written to review.json in the cache, so
`report` shows them in the job summary and the pull request comment, and to --output.
A review that cannot run (no SDK, no credentials, an API error) logs why and exits 0:
it is advisory, so it only fails the job through --fail-on.
"""

import json
import logging
import sys
from argparse import Namespace
from typing import Any

import click

from dbt_ci.commands.report.index import write_report
from dbt_ci.commands.review.claude import (
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    SEVERITIES,
    ReviewSettings,
    make_client,
    review_models,
)
from dbt_ci.commands.review.context import collect_models
from dbt_ci.commands.review.render import render_review
from dbt_ci.errors import DbtCiError
from dbt_ci.utilities.cache import CacheManager
from dbt_ci.utilities.logging import print_exception, redact_namespace

logger = logging.getLogger(__name__)


def review(args: Namespace) -> None:
    """Review the changed models, record the findings and write them out."""
    click.secho("DBT CI Review", fg="green", bold=True)
    logger.debug(f"Running with the following arguments: {redact_namespace(args)}")
    cache = CacheManager(args)
    if cache.get_cache() is None:
        logger.error("No cache found, please run 'dbt-ci init' first.")
        sys.exit(1)
    cache.start_report("review", args)
    try:
        with cache.track_report("review"):
            record = run_review(args, cache)
            cache.write_review(record)
            cache.update_report("review", review_status(record), report_entry(record))
            write_output(record, args)
            exit_code = fail_on_exit_code(record, getattr(args, "fail_on", None))
            sys.exit(exit_code)
    except SystemExit:
        raise
    except Exception as e:
        print_exception(e, "Error during the AI review")
        sys.exit(1)


def run_review(args: Namespace, cache: CacheManager) -> dict[str, Any]:
    """Collect the changed models, review them, and return what review.json records."""
    settings = ReviewSettings(
        model=getattr(args, "model", None) or DEFAULT_MODEL,
        effort=getattr(args, "effort", None) or DEFAULT_EFFORT,
        instructions=getattr(args, "instructions", None),
    )
    collected = collect_models(
        cache,
        exclude=tuple(getattr(args, "exclude", None) or ()),
        max_models=getattr(args, "max_models", None),
    )
    record: dict[str, Any] = {
        "model": settings.model,
        "effort": settings.effort,
        "models": {m["unique_id"]: m.get("name", m["unique_id"]) for m in collected.models},
        "skipped": collected.skipped,
        "findings": [],
        "summaries": [],
        "errors": [],
    }
    for node_id, reason in collected.skipped.items():
        logger.info(f"Not reviewing {node_id}: {reason}")
    if not collected.models:
        logger.info("No changed models to review.")
        return record
    if getattr(args, "dry_run", False):
        names = ", ".join(record["models"].values())
        logger.info(f"Dry run enabled - would send {len(collected.models)} model(s): {names}")
        record["skipped_reason"] = "dry run"
        return record

    try:
        client = make_client()
    except DbtCiError as e:
        logger.warning(f"Skipping the AI review: {e}")
        record["skipped_reason"] = str(e)
        return record

    logger.info(f"Reviewing {len(collected.models)} model(s) with {settings.model}...")
    result = review_models(client, collected.models, settings, collected.adapter)
    record.update(
        findings=result.findings,
        summaries=result.summaries,
        errors=result.errors,
        usage=result.usage,
        served_by=sorted(m for m in result.served_by if m),
    )
    if result.errors and not result.findings and not result.summaries:
        record["skipped_reason"] = "every request to Claude failed; see the log"
    logger.info(
        f"AI review: {len(result.findings)} finding(s); tokens: "
        + ", ".join(f"{k}={v}" for k, v in sorted(result.usage.items()))
    )
    return record


def review_status(record: dict[str, Any]) -> str:
    """Return the review's report status: completed, or skipped when it could not run."""
    return "skipped" if record.get("skipped_reason") else "completed"


def report_entry(record: dict[str, Any]) -> dict[str, Any]:
    """Return the counts recorded in report.json for the review."""
    counts = {s: 0 for s in SEVERITIES}
    for finding in record.get("findings") or []:
        if finding.get("severity") in counts:
            counts[finding["severity"]] += 1
    entry: dict[str, Any] = {
        "model": record.get("model"),
        "reviewed": len(record.get("models") or {}),
        "findings": counts,
    }
    if record.get("skipped_reason"):
        entry["comment"] = record["skipped_reason"]
    return entry


def write_output(record: dict[str, Any], args: Namespace) -> None:
    """Write the review as markdown or JSON to --output, or stdout."""
    if getattr(args, "format", "markdown") == "json":
        rendered = json.dumps(record, indent=2, sort_keys=True)
    else:
        rendered = "\n".join(render_review(record, heading="## dbt-ci AI review")).rstrip() + "\n"
    output = getattr(args, "output", None)
    if output:
        write_report(rendered, Namespace(output=output))
    else:
        click.echo(rendered)


def fail_on_exit_code(record: dict[str, Any], fail_on: str | None) -> int:
    """Return 1 when a finding is at least as severe as --fail-on, else 0."""
    if not fail_on or fail_on == "never":
        return 0
    threshold = SEVERITIES.index(fail_on)
    worst = [
        f for f in record.get("findings") or [] if SEVERITIES.index(f["severity"]) <= threshold
    ]
    if worst:
        logger.error(f"{len(worst)} AI review finding(s) at or above '{fail_on}' (--fail-on).")
        return 1
    return 0
