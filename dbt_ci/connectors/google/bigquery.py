"""BigQuery connector for dbt CI."""

from __future__ import annotations

import logging
from argparse import Namespace
from typing import Any, cast
from dbt_ci.schema import DeleteMapNode, MigrationMap
from dbt_ci.utilities.optional_imports import require

try:  # google-cloud-bigquery ships in the optional "gcp" extra.
    from google.cloud import bigquery
except ImportError:  # pragma: no cover - exercised only without the extra installed
    bigquery = None
from dbt_ci.utilities.paths import get_dbt_project_file, get_profile, get_profiles_file
from dbt_ci.utilities.multi_threading import run_multithreaded

logger = logging.getLogger(__name__)


def bigquery_client(args: Namespace) -> bigquery.Client:
    """Create a BigQuery client using credentials from the dbt profiles.yml file."""
    dbt_project_dir = getattr(args, "dbt_project_dir", None)
    if dbt_project_dir is None:
        raise ValueError("dbt_project_dir argument is required to initialize BigQuery client")

    dbt_profile = get_profiles_file(
        dbt_project_dir=dbt_project_dir, profiles_dir=getattr(args, "profiles_dir", None)
    )

    # Get the profile name from the project config
    profile_name = (get_dbt_project_file(dbt_project_dir) or {}).get("profile")

    if not profile_name:
        raise ValueError("No 'profile' key found in dbt_project.yml")

    profile_config = dbt_profile.get(profile_name, {})

    if not profile_config:
        raise ValueError(f"Profile '{profile_name}' not found in profiles.yml")

    output = profile_config.get("outputs", {}).get(getattr(args, "target", None), {})
    if not output:
        raise ValueError(
            f"No output configuration found for target '{getattr(args, 'target', None)}' in profiles.yml"
        )
    elif output.get("type") != "bigquery":
        raise ValueError(
            f"Output type for target '{getattr(args, 'target', None)}' is not 'bigquery' in profiles.yml"
        )
    elif output.get("project") is None:
        raise ValueError(
            f"No 'project' specified for target '{getattr(args, 'target', None)}' in profiles.yml"
        )
    elif output.get("location") is None:
        raise ValueError(
            f"No 'location' specified for target '{getattr(args, 'target', None)}' in profiles.yml"
        )

    client = require(bigquery, "gcp", "The BigQuery connector").Client(
        project=output.get("project", ""), location=output.get("location", "")
    )

    return client


def bigquery_delete_datasets(
    client: bigquery.Client, datasets_to_delete: set[str], dry_run: bool = False, threads: int = 5
) -> None:
    """Delete datasets in BigQuery."""
    if len(datasets_to_delete) == 0:
        logger.info("No datasets to delete. Exiting dataset deletion step.")
        return
    logger.info("Deleting datasets in BigQuery:")
    for dataset_id in datasets_to_delete:
        logger.info(f"\n  - {dataset_id}")

    if dry_run:
        logger.info("\nDry run mode enabled - no datasets will actually be deleted.")
        return

    # Pass to multi_thread module
    func_list = [
        lambda dataset_id=dataset_id: delete_dataset(client, dataset_id)
        for dataset_id in datasets_to_delete
    ]
    run_multithreaded(func_list=func_list, threads=threads, exit_on_exception=True)


def delete_dataset(client: bigquery.Client, dataset_id: str) -> None:
    """Delete a BigQuery dataset."""
    try:
        client.delete_dataset(dataset_id, delete_contents=True, not_found_ok=True)
        logger.info(f"Dataset '{dataset_id}' deleted successfully.")
    except Exception as e:
        raise RuntimeError(f"Failed to delete dataset '{dataset_id}': {e}")


def bigquery_delete_strategy(delete_map: dict[str, DeleteMapNode], args: Namespace) -> None:
    """Strategy for handling deletes towards BigQuery."""
    # For BigQuery, we will delete tables directly using the BigQuery client.
    # This function can be expanded to handle any pre-deletion logic if needed.
    try:
        client = bigquery_client(args)
        profile = get_profile(args)
        threads: int = cast(int, profile.get("threads", 5) if profile else 5)
        tables_to_delete: set[str] = set()

        for node_metadata in delete_map.values():
            table_id = node_metadata.get("table_id")
            if table_id:
                tables_to_delete.add(table_id)
                tables_to_delete.add(
                    f"{table_id}__dbt_tmp"
                )  # Also delete the dbt temporary table if it exists

        bigquery_delete_tables(client, tables_to_delete, getattr(args, "dry_run", False), threads)
    except Exception as e:
        raise RuntimeError(f"Error in BigQuery delete strategy: {e}")


def bigquery_delete_tables(
    client: bigquery.Client, tables_to_delete: set[str], dry_run: bool = False, threads: int = 5
) -> None:
    """Delete tables in BigQuery."""

    def _delete_table(table_id: str) -> None:
        """Delete a single BigQuery table."""
        try:
            client.delete_table(table_id, not_found_ok=True)
            logger.info(f"Deleted {table_id} from BigQuery")
        except Exception as e:
            logger.error(f"Error deleting {table_id} from BigQuery: {e}")
            raise

    if len(tables_to_delete) == 0:
        logger.info("No tables to delete. Exiting table deletion step.")
        return
    logger.info("Deleting tables in BigQuery:")
    for table_id in tables_to_delete:
        logger.info(f"\n  - {table_id}")

    if dry_run:
        logger.info("\nDry run mode enabled - no tables will actually be deleted.")
        return

    func_list = [lambda table_id=table_id: _delete_table(table_id) for table_id in tables_to_delete]
    run_multithreaded(func_list=func_list, threads=threads, exit_on_exception=True)


def bigquery_migration_strategy(migration_map: MigrationMap, args: Namespace) -> None:
    """Strategy for handling partitioning migrations towards BigQuery."""
    try:
        client = bigquery_client(args)
        profile = get_profile(args)
        if profile is None:
            raise ValueError(
                "No profile found for the specified target. Please check your profiles.yml configuration."
            )

        threads: int = cast(int, profile.get("threads", 5))
        nodes = migration_map["nodes"]

        def migrate_table(node_data: dict) -> None:
            """Migrate a single table's partitioning by recreating it. Steps must run sequentially."""
            table_id: str = node_data["table_id"]
            table_name: str = table_id.split(".")[
                -1
            ]  # RENAME TO only accepts a bare table name, not a fully-qualified path
            temp_table_id: str = f"{table_id}_temp_new_partition"
            backup_table_name: str = f"{table_name}__dbt_ci_backup"
            backup_table_id: str = f"{table_id}__dbt_ci_backup"
            dbt_tmp_table_id: str = f"{table_id}__dbt_tmp"
            table_clauses: str = " ".join(
                filter(
                    None,
                    [
                        render_bigquery_partition_clause(node_data["new_partitioning"]),
                        render_bigquery_cluster_clause(node_data.get("cluster_by")),
                        render_bigquery_options_clause(node_data),
                    ],
                )
            )
            # Step 1: Copy data into a new temp table with the new partitioning spec (and the
            # model's clustering and partition options, which a plain CTAS would drop).
            # Using a new table name avoids the "cannot replace with different partitioning spec" error.
            client.query(
                f"CREATE OR REPLACE TABLE `{temp_table_id}` {table_clauses} AS SELECT * FROM `{table_id}`"
            ).result()
            # Step 2: Move the original table aside instead of dropping it, so a failure in the
            # swap below never leaves production without its data.
            # BigQuery RENAME TO only accepts a bare table name (no project/dataset prefix).
            client.query(f"ALTER TABLE `{table_id}` RENAME TO `{backup_table_name}`").result()
            try:
                # Step 3: Rename the temp table to the original table name.
                client.query(f"ALTER TABLE `{temp_table_id}` RENAME TO `{table_name}`").result()
            except Exception as e:
                raise RuntimeError(
                    f"Renaming the migrated table into place failed for '{table_id}'. The original "
                    f"data is preserved in '{backup_table_id}' and the migrated copy in '{temp_table_id}'. "
                    f"Original error: {e}"
                ) from e
            # Step 4: Only now drop the old table and any leftover dbt tmp table.
            client.query(f"DROP TABLE IF EXISTS `{backup_table_id}`").result()
            client.query(f"DROP TABLE IF EXISTS `{dbt_tmp_table_id}`").result()
            logger.info(f"Migrated partitioning for table '{table_id}'")

        if args.dry_run:
            logger.info("Dry run mode enabled - no changes will be applied.")
            return

        # Each table's steps must run sequentially, but different tables can run in parallel.
        run_multithreaded(
            func_list=[
                lambda node_data=node_data: migrate_table(node_data) for node_data in nodes.values()
            ],
            threads=threads,
            exit_on_exception=True,
        )
    except Exception as e:
        raise RuntimeError(
            f"An error occurred while initializing BigQuery client or processing migration map: {e}"
        )


def render_bigquery_cluster_clause(cluster_by: str | list[str] | None) -> str:
    """Render a BigQuery CLUSTER BY clause from dbt's cluster_by config (a column or list of columns)."""
    if not cluster_by:
        return ""
    columns = [cluster_by] if isinstance(cluster_by, str) else list(cluster_by)
    return "CLUSTER BY " + ", ".join(f"`{column}`" for column in columns)


def render_bigquery_options_clause(node_data: dict[str, Any]) -> str:
    """Render the OPTIONS(...) clause for the partition settings dbt manages on the table."""
    options: list[str] = []
    if node_data.get("require_partition_filter") is not None:
        options.append(
            f"require_partition_filter={'true' if node_data['require_partition_filter'] else 'false'}"
        )
    if node_data.get("partition_expiration_days") is not None:
        options.append(f"partition_expiration_days={float(node_data['partition_expiration_days'])}")
    return f"OPTIONS({', '.join(options)})" if options else ""


def render_bigquery_partition_clause(partition_by: dict[str, Any]) -> str:
    """
    Render a BigQuery PARTITION BY clause from dbt-style partition_by config.

    Supports:
      - timestamp / datetime
      - date
      - int64 range partitioning
      - ingestion-time partitioning

    Returns:
        str: e.g. "PARTITION BY timestamp_trunc(created_at, day)"
    """
    if not partition_by:
        return ""

    field = partition_by.get("field")
    data_type = (partition_by.get("data_type") or "").lower()
    granularity = (partition_by.get("granularity") or "day").lower()
    ingestion = partition_by.get("time_ingestion_partitioning", False)

    if not field:
        raise ValueError("partition_by.field is required")

    if data_type not in {"timestamp", "datetime", "date", "int64"}:
        raise ValueError("partition_by.data_type must be one of: timestamp|datetime|date|int64")

    # ------------------------------------------------------------------
    # Ingestion-time partitioning
    # ------------------------------------------------------------------
    if ingestion:
        if granularity not in {"hour", "day", "month", "year"}:
            raise ValueError("Ingestion-time partitioning supports: hour|day|month|year")
        return f"PARTITION BY timestamp_trunc(_PARTITIONTIME, {granularity})"

    # ------------------------------------------------------------------
    # Integer range partitioning
    # ------------------------------------------------------------------
    if data_type == "int64":
        r = partition_by.get("range") or {}
        start = r.get("start")
        end = r.get("end")
        interval = r.get("interval")

        if None in (start, end, interval):
            raise ValueError(
                "partition_by.range.start/end/interval required for int64 partitioning"
            )

        return "PARTITION BY " f"range_bucket({field}, generate_array({start}, {end}, {interval}))"

    # ------------------------------------------------------------------
    # Date partitioning
    # ------------------------------------------------------------------
    if data_type == "date":
        if granularity == "day":
            return f"PARTITION BY {field}"

        if granularity in {"month", "year"}:
            return f"PARTITION BY date_trunc({field}, {granularity})"

        raise ValueError("Date partitioning supports: day|month|year")

    # ------------------------------------------------------------------
    # Timestamp / Datetime partitioning
    # ------------------------------------------------------------------
    if data_type in {"timestamp", "datetime"}:
        if granularity not in {"hour", "day", "month", "year"}:
            raise ValueError("Timestamp/datetime partitioning supports: hour|day|month|year")

        trunc_fn = "timestamp_trunc" if data_type == "timestamp" else "datetime_trunc"
        return f"PARTITION BY {trunc_fn}({field}, {granularity})"

    raise ValueError(
        "Unsupported partitioning configuration. No PARTITION BY clause will be applied."
    )
