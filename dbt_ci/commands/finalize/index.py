"""The finalize command: upload the run's artifacts, then clear the cache."""

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
    """Upload the run's artifacts to --artifacts-uri and clear the cache.

    With the deprecated --clean-ephemeral it first tears down the ephemeral environment.
    A dry run uploads nothing and keeps the cache.

    Examples:
        dbt-ci finalize
        dbt-ci finalize --artifacts-uri s3://my-bucket/dbt-artifacts/
    """
    try:
        click.secho("DBT CI Finalize", fg="green", bold=True)
        logger.debug(f"Running with the following arguments: {redact_namespace(args)}")
        cache = CacheManager(args)
        logger.info("Finalizing ci/cd process by uploading manifest.json and cleaning up cache...")
        cache.start_report("finalize", args)
        dry_run = getattr(args, "dry_run", False)

        # Tear down first: a missing manifest or a failed upload below exits early, and
        # must not leave the CI datasets behind. A failed teardown in turn must not
        # block the upload, so it is reported once the rest has run.
        cleanup_error: Exception | None = None
        if getattr(args, "clean_ephemeral", False):
            try:
                clean_up_ephemeral(args, cache)
            except Exception as e:
                print_exception(e, "Ephemeral cleanup failed")
                cleanup_error = e

        manifest_file = cache.get_cache("target_manifest.json") or cache.get_cache(
            "reference_manifest.json"
        )
        if manifest_file is None:
            logger.warning("No manifest file found in cache to upload. Skipping artifact upload.")
            sys.exit(1)

        # Upload files to storage if artifacts_uri is provided. A dry run must not
        # touch the artifacts location, which is often where production state lives.
        if dry_run:
            if getattr(args, "artifacts_uri", None):
                logger.info(
                    "Dry run enabled - skipping upload of "
                    f"{list(getattr(args, 'files', []) or [])} to {args.artifacts_uri}."
                )
        else:
            finalize_upload_files(args)

        if cleanup_error is not None:
            # Keep the cache: it holds the ephemeral map a re-run needs to retry the teardown.
            cache.update_report(
                "finalize", "failed", comment=f"Ephemeral cleanup failed: {cleanup_error}"
            )
            sys.exit(1)

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
