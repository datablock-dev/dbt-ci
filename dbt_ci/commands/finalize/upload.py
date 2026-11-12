import logging
from argparse import Namespace
from functools import partial
from typing import Any, Callable, cast
from dbt_ci.utilities.cache import CacheManager
from dbt_ci.connectors import init_storage_connector
from dbt_ci.commands.finalize.publish_order import (
    COMMIT_RECORD,
    Commit,
    commit_record,
    commit_time,
    current_commit_sha,
    published_is_newer,
    read_published_commit,
)
from dbt_ci.dbt.flags import get_cached_value
from dbt_ci.schema import StorageConnectorConfig
from dbt_ci.utilities.ci_event import PULL_REQUEST, resolve_event
from dbt_ci.utilities.uri_placeholders import resolve_uri_placeholders
from dbt_ci.utilities.run_times import RUN_TIMES_FILE, download_run_times, merge_times
from dbt_ci.utilities.logging import LOG_FILE_NAME, flush_log_file

logger = logging.getLogger(__name__)


def finalize_upload_files(args: Namespace) -> None:
    """Upload files to specified storage location if artifacts_uri is provided in arguments."""
    cache = CacheManager(args)
    artifacts_uri = getattr(args, "artifacts_uri", None)
    if artifacts_uri is None:
        return
    # {pr} and {branch} are filled in before anything else, so the pull request guard
    # below compares the location the files would really go to
    artifacts_uri = resolve_uri_placeholders(artifacts_uri, "--artifacts-uri")
    # "gs://bucket/path/" would otherwise upload to "gs://bucket/path//manifest.json"
    artifacts_uri = artifacts_uri.rstrip("/")

    init_storage = init_storage_connector(artifacts_uri)

    if init_storage is None:
        logger.warning(
            "No valid storage connector found for artifact upload. Skipping artifact upload."
        )
        return

    resolved_storage, _ = init_storage
    if publishes_pull_request_over_production(args, artifacts_uri):
        return logger.warning(
            f"Not uploading to {artifacts_uri}: this run is for a pull request, and that is "
            "where init reads the production state from. Give pull requests their own "
            "location (on: pull-request: finalize: artifacts-uri: ...), or pass "
            "--force-manifest to publish anyway."
        )
    storage_function = resolved_storage.get("upload")
    if storage_function is None:
        logger.warning(
            "No upload function found for resolved storage connector. Skipping artifact upload."
        )
        return

    if not getattr(args, "files", None) or len(getattr(args, "files", [])) == 0:
        logger.info(
            "No files specified for upload. Please specify which files to upload using the "
            "--files argument. Skipping artifact upload."
        )
        return

    for file in getattr(args, "files", []):
        upload_func = UPLOAD_MAPPING.get(file)
        if upload_func is upload_manifest:
            upload_func = partial(
                upload_manifest,
                connector=resolved_storage,
                force=bool(getattr(args, "force_manifest", False)),
            )
        if upload_func is None:
            logger.warning(
                f"No upload function found for file type '{file}'. Skipping upload for this file "
                "type."
            )
            continue
        upload_func(artifacts_uri, cache, storage_function)


def publishes_pull_request_over_production(args: Namespace, artifacts_uri: str) -> bool:
    """
    Report whether a pull request run would upload to where the production state lives.

    The state init downloads is meant to be production's, so a pull request publishing
    there would make later pull requests compare against an unmerged branch.
    `artifacts_uri` must already have its placeholders resolved.
    """
    if getattr(args, "force_manifest", False):
        return False
    state_uri = getattr(args, "state_uri", None) or get_cached_value(args, "reference_state_uri")
    if not state_uri:
        return False
    if artifacts_uri.rstrip("/") != state_directory(state_uri).rstrip("/"):
        return False
    try:
        event = resolve_event(
            getattr(args, "event", None), base_branch=get_cached_value(args, "base_ref")
        )
    except ValueError:
        return False
    return event.name == PULL_REQUEST


def state_directory(state_uri: str) -> str:
    """Return the folder a state URI's manifest sits in, where finalize publishes it."""
    return state_uri.rsplit("/", 1)[0] if state_uri.endswith(".json") else state_uri


def upload_cache(
    artifacts_uri: str, cache: CacheManager, storage_function: Callable[[str, Any, str], None]
) -> None:
    """Upload cache file to storage."""
    cache_file = cache.get_cache()
    if cache_file is None:
        return logger.warning("No cache file found for upload, skipping...")
    storage_function(f"{artifacts_uri}/cache.json", cache_file, "application/json")
    logger.info(f"Uploading cache.json to {artifacts_uri}/cache.json...")


def upload_logs(
    artifacts_uri: str, cache: CacheManager, storage_function: Callable[[str, Any, str], None]
) -> None:
    """Upload the run's log file to storage."""
    # Records still sitting in the handler's buffer would otherwise be missing from the
    # uploaded copy, since the handler stays attached for the rest of the command.
    flush_log_file()
    logs = cache.get_cache_text(LOG_FILE_NAME)
    if not logs:
        return logger.warning("No logs found for upload, skipping...")
    storage_function(f"{artifacts_uri}/logs.txt", logs, "text/plain")
    logger.info(f"Uploading logs to {artifacts_uri}/logs.txt...")


def upload_manifest(
    artifacts_uri: str,
    cache: CacheManager,
    storage_function: Callable[[str, Any, str], None],
    connector: StorageConnectorConfig | None = None,
    force: bool = False,
) -> None:
    """
    Upload the manifest as the latest state, and a copy for the commit it was built from.

    With a connector to read the published state, manifest.json is only replaced when
    it does not come from a newer commit than this one, unless force is set (see
    publish_order).
    """
    manifest_file = cast(
        dict | None,
        cache.get_cache("target_manifest.json") or cache.get_cache("reference_manifest.json"),
    )
    if manifest_file is None:
        return logger.warning("No manifest file found for upload, skipping...")

    sha = current_commit_sha()
    commit = Commit(sha, commit_time(sha)) if sha else None

    # Keep a copy per commit as well, so pull requests can compare against the manifest
    # of the commit their branch started from (init --compare-to auto / merge-base). It
    # is right for its commit whatever was published since, so it is always uploaded.
    if commit:
        storage_function(
            f"{artifacts_uri}/{commit.sha}/manifest.json", manifest_file, "application/json"
        )
        logger.info(
            f"Keeping a copy for commit {commit.sha[:12]} at "
            f"{artifacts_uri}/{commit.sha}/manifest.json"
        )
    else:
        logger.debug("No commit found, so no per-commit copy of the manifest was kept.")

    # Measured times are right whichever manifest ends up published
    if connector:
        publish_run_times(artifacts_uri, cache, storage_function, connector)

    published = read_published_commit(artifacts_uri, connector) if connector else None
    if commit and published and published_is_newer(commit, published):
        if not force:
            return logger.warning(
                f"Not replacing {artifacts_uri}/manifest.json: it was built from commit "
                f"{published.sha[:12]}, which is newer than this run's {commit.sha[:12]} "
                "(e.g. a later deploy finished first, or an older run was re-run). Pass "
                "--force-manifest to replace it anyway, e.g. to roll back."
            )
        logger.warning(
            f"Replacing the manifest of the newer commit {published.sha[:12]} with this "
            f"run's {commit.sha[:12]} (--force-manifest)."
        )

    storage_function(f"{artifacts_uri}/manifest.json", manifest_file, "application/json")
    logger.info(f"Uploading manifest.json to {artifacts_uri}/manifest.json...")
    storage_function(f"{artifacts_uri}/{COMMIT_RECORD}", commit_record(commit), "application/json")


def publish_run_times(
    artifacts_uri: str,
    cache: CacheManager,
    storage_function: Callable[[str, Any, str], None],
    connector: StorageConnectorConfig,
) -> None:
    """Merge the node times this run measured into run_times.json next to the manifest."""
    measured = (cache.get_cache(RUN_TIMES_FILE) or {}).get("this_run") or {}
    if not measured:
        return
    uri = f"{artifacts_uri}/{RUN_TIMES_FILE}"
    published = {"nodes": download_run_times(uri, connector)}
    storage_function(uri, merge_times(published, measured), "application/json")
    logger.info(f"Recorded the run times of {len(measured)} node(s) in {uri}")


UPLOAD_MAPPING: dict[str, Callable[[str, CacheManager, Callable[[str, Any, str], None]], None]] = {
    "manifest": upload_manifest,
    "cache": upload_cache,
    "log": upload_logs,
}
