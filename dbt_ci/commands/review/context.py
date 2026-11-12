"""
Collect what the AI review sees of each changed model.

Everything comes from what `init` cached: the change set and why each node is in it,
the pull request's and production's manifests, and the run times recorded by earlier
deploys. Only code and metadata are collected, never data from the warehouse.
"""

import difflib
import logging
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any, Sequence

from dbt_ci.utilities.cache import CacheManager
from dbt_ci.utilities.run_times import RUN_TIMES_FILE

logger = logging.getLogger(__name__)

# Resource types whose SQL is worth reviewing
REVIEWED_TYPES = ("model", "snapshot")
# Config keys that shape how a model is built and what it costs
CONFIG_KEYS = (
    "materialized",
    "incremental_strategy",
    "unique_key",
    "on_schema_change",
    "partition_by",
    "cluster_by",
    "sort",
    "dist",
    "full_refresh",
    "contract",
    "strategy",
    "updated_at",
    "check_cols",
)


@dataclass
class ReviewInput:
    """The changed models to review, the ones left out and why, and the warehouse."""

    models: list[dict[str, Any]] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    adapter: str | None = None


def collect_models(
    cache: CacheManager, exclude: Sequence[str] = (), max_models: int | None = None
) -> ReviewInput:
    """
    Return the context of every changed model and snapshot, in the change set's order.

    Models whose path matches one of `exclude` (fnmatch patterns) are left out, and so
    are the ones past `max_models`, the slowest first being kept so the cap drops the
    cheapest models.
    """
    changes = cache.get_cache() or {}
    target = cache.get_cache("target_manifest.json") or {}
    reference = cache.get_cache("reference_manifest.json") or {}
    run_times = cache.get_cache(RUN_TIMES_FILE) or {}
    recorded: dict[str, float] = run_times.get("recorded") or {}
    reasons: dict[str, list[str]] = changes.get("reasons") or {}
    result = ReviewInput(adapter=(target.get("metadata") or {}).get("adapter_type"))

    candidates: list[tuple[str, str]] = []
    for change_key, change in (("modified_nodes", "modified"), ("new_nodes", "new")):
        for resource_type, nodes in sorted((changes.get(change_key) or {}).items()):
            if resource_type not in REVIEWED_TYPES:
                continue
            candidates.extend((node_id, change) for node_id in nodes)

    kept: list[tuple[str, str]] = []
    for node_id, change in candidates:
        node = (target.get("nodes") or {}).get(node_id)
        if node is None:
            result.skipped[node_id] = "not in the pull request's manifest"
            continue
        path = node.get("original_file_path") or ""
        pattern = next((p for p in exclude if fnmatchcase(path, p)), None)
        if pattern:
            result.skipped[node_id] = f"excluded by {pattern}"
            continue
        kept.append((node_id, change))

    if max_models is not None and len(kept) > max_models:
        by_cost = sorted(kept, key=lambda item: -(recorded.get(item[0]) or 0.0))
        for node_id, _ in by_cost[max_models:]:
            result.skipped[node_id] = f"over review.max-models ({max_models})"
        allowed = {node_id for node_id, _ in by_cost[:max_models]}
        kept = [item for item in kept if item[0] in allowed]

    for node_id, change in kept:
        result.models.append(
            model_context(node_id, change, target, reference, reasons, recorded.get(node_id))
        )
    return result


def model_context(
    node_id: str,
    change: str,
    target: dict[str, Any],
    reference: dict[str, Any],
    reasons: dict[str, list[str]],
    run_seconds: float | None,
) -> dict[str, Any]:
    """Return what the review is told about one model, leaving out empty values."""
    node = target["nodes"][node_id]
    config = node.get("config") or {}
    children = (target.get("child_map") or {}).get(node_id) or []
    nodes = target.get("nodes") or {}
    exposures = target.get("exposures") or {}
    columns = node.get("columns") or {}
    context: dict[str, Any] = {
        "unique_id": node_id,
        "name": node.get("name"),
        "path": node.get("original_file_path"),
        "change": change,
        "why_changed": reasons.get(node_id) or [],
        "config": build_config(config),
        "sql": node.get("compiled_code") or node.get("raw_code") or "",
        "sql_is_compiled": bool(node.get("compiled_code")),
        "tests": sorted(
            nodes[child].get("name", child) for child in children if child.startswith("test.")
        ),
        "downstream_models": sum(1 for child in children if child.startswith("model.")),
        "exposures": sorted(
            exposures[child].get("name", child) for child in children if child in exposures
        ),
        "has_description": bool((node.get("description") or "").strip()),
        "documented_columns": sorted(columns),
        "recorded_run_seconds": round(run_seconds, 1) if run_seconds else None,
    }
    previous = ((reference.get("nodes") or {}).get(node_id) or {}).get("raw_code")
    if change == "modified" and previous is not None:
        context["source_diff"] = source_diff(previous, node.get("raw_code") or "", context["path"])
    return {key: value for key, value in context.items() if value not in (None, [], {}, "")}


def build_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return the config keys that shape the build, without defaults that say nothing."""
    kept = {key: config[key] for key in CONFIG_KEYS if config.get(key) not in (None, "")}
    if not (kept.get("contract") or {}).get("enforced"):
        kept.pop("contract", None)
    if kept.get("materialized") != "incremental":
        # Only incremental models act on these
        for key in ("incremental_strategy", "on_schema_change"):
            kept.pop(key, None)
    return kept


def source_diff(before: str, after: str, path: str | None) -> str:
    """Return a unified diff of a model's source between production and the pull request."""
    name = path or "model.sql"
    # Compared line by line without line endings, so a file that does not end in a
    # newline does not run two lines of the diff together
    return "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"production/{name}",
            tofile=f"pull-request/{name}",
            lineterm="",
        )
    )
