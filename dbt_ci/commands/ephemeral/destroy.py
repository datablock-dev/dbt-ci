"""Tear down the environment that `dbt-ci ephemeral` created."""

import sys
import logging
from argparse import Namespace
from typing import cast
import click
from dbt_ci.connectors import get_connector
from dbt_ci.dbt.operations import SchemaRef, drop_schemas
from dbt_ci.dbt.flags import apply_cached_config
from dbt_ci.graph.dependency_graph import DbtGraph
from dbt_ci.schema import EphemeralMapNode, NodeConfig
from dbt_ci.errors import DbtCiError
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
    # Adapters without a native connector drop their schemas through dbt instead
    delete_datasets_function = (connector or {}).get("methods", {}).get("delete_datasets")

    ephemeral_map = cast(dict[str, EphemeralMapNode] | None, cache.get_cache("ephemeral_map.json"))
    if ephemeral_map is None:
        logger.warning("No ephemeral map found in cache to clean up. Skipping ephemeral cleanup.")
        return

    # Get unique datasets to delete, keeping their parts for adapters that need them
    dataset_refs: dict[str, SchemaRef] = {}
    for node_info in ephemeral_map.values():
        config = node_info.get("ephemeral_config")
        dataset_id = get_dataset_id(config)
        if config is not None and dataset_id is not None:
            dataset_refs[dataset_id] = {
                "database": config.get("database"),
                "schema": cast(str, config["schema"]),
            }
    datasets_to_delete = set(dataset_refs)

    protected_datasets = get_reference_datasets(args, cache)
    for node_info in ephemeral_map.values():
        reference_dataset = get_dataset_id(node_info.get("reference_config"))
        if reference_dataset is not None:
            protected_datasets.add(reference_dataset)

    # Compared case-insensitively: on Snowflake and most other warehouses ANALYTICS and
    # analytics are the same schema, and refusing too much is the safe side.
    protected_lower = {dataset_id.lower() for dataset_id in protected_datasets}
    refused = {
        dataset_id for dataset_id in datasets_to_delete if dataset_id.lower() in protected_lower
    }
    for dataset_id in sorted(refused):
        logger.warning(
            f"Refusing to delete dataset '{dataset_id}': it is used by the reference (production) manifest."
        )
    datasets_to_delete -= refused

    if len(datasets_to_delete) == 0:
        logger.info("No ephemeral datasets found to clean up.")
        return

    logger.info(
        f"Found {len(datasets_to_delete)} ephemeral dataset(s) to clean up: {', '.join(sorted(datasets_to_delete))}"
    )
    dry_run = getattr(args, "dry_run", False)
    if connector is None or delete_datasets_function is None:
        if dry_run:
            logger.info("Dry run mode enabled - no datasets will actually be deleted.")
            return
        drop_schemas(args, [dataset_refs[dataset_id] for dataset_id in sorted(datasets_to_delete)])
        return

    # A dry run only lists the datasets, so it must not need warehouse credentials
    client = None if dry_run else connector["client"](args)
    delete_datasets_function(client, datasets_to_delete, dry_run, threads)


def get_dataset_id(config: NodeConfig | None) -> str | None:
    """
    Return the `database.schema` dataset of a relation config, or None without a schema.

    Adapters without databases (e.g. Spark) leave database empty; their datasets are
    identified by the schema alone.
    """
    if not config or not config.get("schema"):
        return None
    if config.get("database"):
        return f"{config['database']}.{config['schema']}"
    return str(config["schema"])


def get_reference_datasets(args: Namespace, cache: CacheManager) -> set[str]:
    """Collect every dataset that a node in the reference (production) manifest lives in."""
    if cache.get_cache("reference_manifest.json") is None:
        raise DbtCiError(
            "No reference manifest found in cache, so production datasets cannot be protected. Refusing to clean up the ephemeral environment."
        )
    reference_graph = DbtGraph(args, is_reference=True).to_dict()
    datasets: set[str] = set()
    for node_type in ("model", "seed", "snapshot", "source", "test"):
        for node in (reference_graph.get(node_type) or {}).values():
            dataset_id = get_dataset_id(cast(NodeConfig, node))
            if dataset_id is not None:
                datasets.add(dataset_id)
    return datasets
