import sys
import logging
from argparse import Namespace
from typing import Any, Callable, cast
from dbt_ci.utilities.cache import CacheManager
from dbt_ci.connectors import init_storage_connector
from dbt_ci.utilities.logging import LOG_FILE_NAME, flush_log_file, print_exception

logger = logging.getLogger(__name__)

def finalize_upload_files(args: Namespace) -> None:
    """Upload files to specified storage location if artifacts_uri is provided in arguments."""
    try:
        cache = CacheManager(args)
        artifacts_uri = getattr(args, "artifacts_uri", None)
        if artifacts_uri is None:
            return

        init_storage = init_storage_connector(artifacts_uri)
            
        if init_storage is None:
            logger.warning("No valid storage connector found for artifact upload. Skipping artifact upload.")
            return

        resolved_storage, _ = init_storage
        storage_function = resolved_storage.get("upload")
        if storage_function is None:
            logger.warning("No upload function found for resolved storage connector. Skipping artifact upload.")
            return

        if not getattr(args, "files", None) or len(getattr(args, "files", [])) == 0:
            logger.info("No files specified for upload. Please specify which files to upload using the --files argument. Skipping artifact upload.")
            return

        for file in getattr(args, "files", []):
            upload_func = UPLOAD_MAPPING.get(file)
            if upload_func is None:
                logger.warning(f"No upload function found for file type '{file}'. Skipping upload for this file type.")
                continue
            upload_func(artifacts_uri, cache, storage_function)

    except Exception as e:
        print_exception(e, "Error during artifact upload")
        sys.exit(1)

def upload_cache(
    artifacts_uri: str,
    cache: CacheManager,
    storage_function: Callable[[str, Any, str], None]
) -> None:
    """Upload cache file to storage."""
    cache_file = cache.get_cache()
    if cache_file is None:
        return logger.warning("No cache file found for upload, skipping...")
    storage_function(f"{artifacts_uri}/cache.json", cache_file, "application/json")
    logger.info(f"Uploading cache.json to {artifacts_uri}/cache.json...")

def upload_logs(
    artifacts_uri: str,
    cache: CacheManager,
    storage_function: Callable[[str, Any, str], None]
) -> None:
    """Upload the run's log file to storage."""
    # Records still sitting in the handler's buffer would otherwise be missing from the
    # uploaded copy, since the handler stays attached for the rest of the command.
    flush_log_file()
    logs = cast(str | None, cache.get_cache(LOG_FILE_NAME, "txt"))
    if not logs:
        return logger.warning("No logs found for upload, skipping...")
    storage_function(f"{artifacts_uri}/logs.txt", logs, "text/plain")
    logger.info(f"Uploading logs to {artifacts_uri}/logs.txt...")

def upload_manifest(
    artifacts_uri: str,
    cache: CacheManager,
    storage_function: Callable[[str, Any, str], None]
) -> None:
    """Upload manifest file to storage."""
    manifest_file = cast(dict | None, cache.get_cache("target_manifest.json") or cache.get_cache("reference_manifest.json"))
    if manifest_file is None:
        return logger.warning("No manifest file found for upload, skipping...")
    storage_function(f"{artifacts_uri}/manifest.json", manifest_file, "application/json")
    logger.info(f"Uploading manifest.json to {artifacts_uri}/manifest.json...")

UPLOAD_MAPPING: dict[str, Callable[[str, CacheManager, Callable[[str, Any, str], None]], None]] = {
    "manifest": upload_manifest,
    "cache": upload_cache,
    "log": upload_logs
}
