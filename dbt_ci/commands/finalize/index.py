"""Command to finalize the ephemeral environment by replacing references with actual targets."""
import sys
import logging
from argparse import Namespace
import click
from dbt_ci.utilities.cache import CacheManager
from dbt_ci.commands.finalize.upload import finalize_upload_files
from dbt_ci.connectors import get_connector
from dbt_ci.logging import print_exception
from dbt_ci.schema import EphemeralMapNode
from dbt_ci.utilities.paths import get_profile

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
        logger.debug(f"Running with the following arguments: {args}")
        cache = CacheManager(args)
        logger.info("Finalizing ci/cd process by uploading manifest.json and cleaning up cache...")
        manifest_file = cache.get_cache("target_manifest.json") or cache.get_cache("reference_manifest.json")
        cache.start_report("finalize", args)
        if manifest_file is None:
            logger.warning("No manifest file found in cache to upload. Skipping artifact upload.")
            sys.exit(1)

        # Upload files to storage if artifacts_uri is provided
        finalize_upload_files(args)

        if getattr(args, "clean_ephemeral", False):
            clean_up_ephemeral(args, cache)

        cache.update_report("finalize", "completed", cache.get_cache())
        
        cache.clear_cache()
        logger.info("Finalize complete.")
        sys.exit(0)
    except Exception as e:
        print_exception(e)
        sys.exit(1)

def clean_up_ephemeral(args: Namespace, cache: CacheManager):
    """Clean up any ephemeral tables or resources created during the ephemeral step."""
    try:
        logger.info("Cleaning up ephemeral environment...")
        ephemeral_map: dict[str, EphemeralMapNode] = cache.get_cache("ephemeral_map.json")
        profile = get_profile(args)
        threads = profile.get("threads", 5)
        connector_type = profile["type"]
        connector = get_connector(connector_type)
        client = connector.get("client")
        delete_datasets_function = connector.get("methods", {}).get("delete_datasets")

        # Ensure delete function exists for the connector type
        if delete_datasets_function is None:
            logger.warning(f"No delete function found for connector type '{connector_type}'. Skipping ephemeral cleanup.")
            return

        if ephemeral_map is None:
            logger.warning("No ephemeral map found in cache to clean up. Skipping ephemeral cleanup.")
            return
        
        # Get unique schemas/datasets to delete
        datasets_to_delete = set()
        for node_info in ephemeral_map.values():
            ephemeral_schema = node_info.get("ephemeral_config").get("schema", None)
            if ephemeral_schema is not None:
                datasets_to_delete.add(ephemeral_schema)

        if len(datasets_to_delete) == 0:
            logger.info("No ephemeral datasets found to clean up.")
            return
        
        logger.info(f"Found {len(datasets_to_delete)} ephemeral dataset(s) to clean up: {', '.join(datasets_to_delete)}")
        delete_datasets_function(client, datasets_to_delete, getattr(args, "dry_run", False), threads)
    except Exception as e:
        logger.error(f"An error occurred during ephemeral cleanup: {str(e)}")
        return
