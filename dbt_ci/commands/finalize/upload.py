import sys
import logging
from argparse import Namespace
from dbt_ci.utilities.cache import CacheManager
from dbt_ci.connectors import init_storage_connector
from dbt_ci.utilities.logging import print_exception

logger = logging.getLogger(__name__)

def finalize_upload_files(args: Namespace) -> None:
    """"""
    try:
        if getattr(args, "artifacts_uri", None) is None:
            return

        cache = CacheManager(args)
        manifest_file = cache.get_cache("target_manifest.json") or cache.get_cache("reference_manifest.json")
        init_storage = init_storage_connector(getattr(args, "artifacts_uri", None))
            
        if init_storage is None:
            logger.warning("No valid storage connector found for artifact upload. Skipping artifact upload.")
            sys.exit(1)

        resolved_storage, _ = init_storage
        storage_function = resolved_storage.get("upload")
        if storage_function is None:
            logger.warning("No upload function found for resolved storage connector. Skipping artifact upload.")
            sys.exit(1)

        storage_function("manifest.json", manifest_file)
        logger.info(f"Uploading manifest.json to {getattr(args, 'artifacts_uri', None)}...")
        # Upload manifest file to storage if artifacts_uri is provided
        #if report is not None:
        #    logger.info(f"Uploading report.json to {getattr(args, 'artifacts_uri', None)}...")
        #    storage_function("report.json", report)
        #    # Upload report file to storage if artifacts_uri is provided

    except Exception as e:
        print_exception(e, "Error during artifact upload")
        sys.exit(1)