"""Command to finalize the ephemeral environment by replacing references with actual targets."""
import sys
import logging
from argparse import Namespace
import click

from src.cache import CacheManager
from src.connectors import init_storage_connector
from src.logging import print_exception
from src.variables import Variables

logger = logging.getLogger(__name__)

def finalize(**kwargs):
    """Finalize the ephemeral environment by replacing references with actual targets.
    
    This command should be run after the ephemeral environment has been created and tested. It will replace all references to ephemeral tables with the actual target tables in the production environment.
    
    Examples:
        dbt-ci finalize
        dbt-ci finalize --artifacts-uri s3://my-bucket/dbt-artifacts/
    """
    try:
        click.secho("DBT CI Finalize", fg="green", bold=True)
        args = Namespace(**kwargs)
        cache = CacheManager()
        config = Variables(args)
        variables = config.to_namespace()
        logger.info("Finalizing ci/cd process by uploading manifest.json and cleaning up cache...")
        manifest_file = cache.get_cache("target_manifest.json") or cache.get_cache("reference_manifest.json")
        cache.start_report("finalize", variables)
        report = cache.get_cache("report.json")
        if manifest_file is None:
            logger.warning("No manifest file found in cache to upload. Skipping artifact upload.")
            sys.exit(1)

        if variables.artifacts_uri:
            resolved_storage = init_storage_connector(variables.artifacts_uri)
            if resolved_storage is None:
                logger.warning("No valid storage connector found for artifact upload. Skipping artifact upload.")

            resolved_storage["upload"]("manifest.json", manifest_file)
            logger.info(f"Uploading manifest.json to {variables.artifacts_uri}...")
            # Upload manifest file to storage if artifacts_uri is provided
            if report is not None:
                logger.info(f"Uploading report.json to {variables.artifacts_uri}...")
                resolved_storage["upload"]("report.json", report)
                # Upload report file to storage if artifacts_uri is provided
        else:
            if report is not None:
                logger.info(report)
        cache.update_report("finalize", "completed", cache.get_cache())
        logger.info("Finalize complete.")
        sys.exit(0)
    except Exception as e:
        print_exception(e)
        sys.exit(1)
