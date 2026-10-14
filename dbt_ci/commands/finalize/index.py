"""Command to finalize the ephemeral environment by replacing references with actual targets."""
import sys
import logging
from argparse import Namespace
import click
from dbt_ci.utilities.cache import CacheManager
from dbt_ci.commands.ephemeral.destroy import clean_up_ephemeral
from dbt_ci.commands.finalize.upload import finalize_upload_files
from dbt_ci.utilities.logging import print_exception, redact_namespace

logger = logging.getLogger(__name__)

def finalize(args: Namespace):
    """Finalize the ephemeral environment by replacing references with actual targets.
    
    This command should be run after the ephemeral environment has been created and tested. It will replace all references to ephemeral tables with the actual target tables in the production environment.
    
    Examples:
        dbt-ci finalize
        dbt-ci finalize --artifacts-uri s3://my-bucket/dbt-artifacts/
    """
    try:
        click.secho("DBT CI Finalize", fg="green", bold=True)
        logger.debug(f"Running with the following arguments: {redact_namespace(args)}")
        cache = CacheManager(args)
        logger.info("Finalizing ci/cd process by uploading manifest.json and cleaning up cache...")
        manifest_file = cache.get_cache("target_manifest.json") or cache.get_cache("reference_manifest.json")
        cache.start_report("finalize", args)
        if manifest_file is None:
            logger.warning("No manifest file found in cache to upload. Skipping artifact upload.")
            sys.exit(1)

        dry_run = getattr(args, "dry_run", False)

        # Upload files to storage if artifacts_uri is provided. A dry run must not
        # touch the artifacts location, which is often where production state lives.
        if dry_run:
            if getattr(args, "artifacts_uri", None):
                logger.info(f"Dry run enabled - skipping upload of {list(getattr(args, 'files', []) or [])} to {args.artifacts_uri}.")
        else:
            finalize_upload_files(args)

        if getattr(args, "clean_ephemeral", False):
            clean_up_ephemeral(args, cache)

        cache.update_report("finalize", "completed", cache.get_cache())

        if dry_run:
            logger.info("Dry run enabled - keeping the cache.")
        else:
            cache.clear_cache()
        logger.info("Finalize complete.")
        sys.exit(0)
    except Exception as e:
        print_exception(e)
        sys.exit(1)
