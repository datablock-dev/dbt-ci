"""Tear down the environment that `dbt-ci ephemeral` created."""
import sys
import logging
from argparse import Namespace
from typing import cast
import click
from dbt_ci.connectors import get_connector
from dbt_ci.dbt.flags import apply_cached_config
from dbt_ci.graph.dependency_graph import DbtGraph
from dbt_ci.schema import EphemeralMapNode, NodeConfig
from dbt_ci.utilities.cache import CacheManager
from dbt_ci.utilities.logging import print_exception, redact_namespace
from dbt_ci.utilities.paths import get_profile

logger = logging.getLogger(__name__)


def destroy(args: Namespace) -> None:
    """
    Drop the datasets `dbt-ci ephemeral` cloned into, leaving the cache in place.

    Unlike `finalize`, nothing is uploaded and the cache is kept, so this can run in an
    `if: always()` step at any point after `ephemeral`, and a failed teardown can be
    retried by running it again.
    """
    try:
        click.secho("DBT CI Ephemeral Destroy", fg="green", bold=True)
        logger.debug(f"Running with the following arguments: {redact_namespace(args)}")
        # The target selects the warehouse credentials; reuse the one init recorded.
        apply_cached_config(args)
        clean_up_ephemeral(args, CacheManager(args))
        sys.exit(0)
    except Exception as e:
        print_exception(e, "Ephemeral teardown failed")
        sys.exit(1)


def clean_up_ephemeral(args: Namespace, cache: CacheManager):
    """
    Drop the datasets that `ephemeral` cloned into.

    Any dataset that a node in the reference (production) manifest lives in is refused,
    so a CI target that resolves to production schemas can never be wiped. Errors are
    re-raised so that a failed cleanup fails the finalize step.
    """
    logger.info("Cleaning up ephemeral environment...")
    profile = get_profile(args)
    threads = profile.get("threads", 5)
    connector_type = profile["type"]
    connector = get_connector(connector_type)
    delete_datasets_function = (connector or {}).get("methods", {}).get("delete_datasets")

    # Ensure delete function exists for the connector type
    if connector is None or delete_datasets_function is None:
        logger.warning(f"No delete function found for connector type '{connector_type}'. Skipping ephemeral cleanup.")
        return

    ephemeral_map = cast(dict[str, EphemeralMapNode] | None, cache.get_cache("ephemeral_map.json"))
    if ephemeral_map is None:
        logger.warning("No ephemeral map found in cache to clean up. Skipping ephemeral cleanup.")
        return

    # Get unique datasets to delete
    datasets_to_delete: set[str] = set()
    for node_info in ephemeral_map.values():
        dataset_id = get_dataset_id(node_info.get("ephemeral_config"))
        if dataset_id is not None:
            datasets_to_delete.add(dataset_id)

    protected_datasets = get_reference_datasets(args, cache)
    for node_info in ephemeral_map.values():
        reference_dataset = get_dataset_id(node_info.get("reference_config"))
        if reference_dataset is not None:
            protected_datasets.add(reference_dataset)

    refused = datasets_to_delete & protected_datasets
    for dataset_id in sorted(refused):
        logger.warning(f"Refusing to delete dataset '{dataset_id}': it is used by the reference (production) manifest.")
    datasets_to_delete -= refused

    if len(datasets_to_delete) == 0:
        logger.info("No ephemeral datasets found to clean up.")
        return

    logger.info(f"Found {len(datasets_to_delete)} ephemeral dataset(s) to clean up: {', '.join(sorted(datasets_to_delete))}")
    dry_run = getattr(args, "dry_run", False)
    # A dry run only lists the datasets, so it must not need warehouse credentials
    client = None if dry_run else connector["client"](args)
    delete_datasets_function(client, datasets_to_delete, dry_run, threads)


def get_dataset_id(config: NodeConfig | None) -> str | None:
    """Return the `database.schema` dataset of a relation config, or None if it is incomplete."""
    if not config or not config.get("database") or not config.get("schema"):
        return None
    return f"{config['database']}.{config['schema']}"


def get_reference_datasets(args: Namespace, cache: CacheManager) -> set[str]:
    """Collect every dataset that a node in the reference (production) manifest lives in."""
    if cache.get_cache("reference_manifest.json") is None:
        raise RuntimeError("No reference manifest found in cache, so production datasets cannot be protected. Refusing to clean up the ephemeral environment.")
    reference_graph = DbtGraph(args, is_reference=True).to_dict()
    datasets: set[str] = set()
    for node_type in ("model", "seed", "snapshot", "source", "test"):
        for node in (reference_graph.get(node_type) or {}).values():
            if node.get("database") and node.get("schema"):
                datasets.add(f"{node['database']}.{node['schema']}")
    return datasets
