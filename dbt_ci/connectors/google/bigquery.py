"""BigQuery connector for dbt CI."""
import logging
from argparse import Namespace
from typing import Any, cast
from google.cloud import bigquery
from dbt_ci.schema import DeleteMapNode, EphemeralMapNode, MigrationMap
from dbt_ci.utilities.paths import get_profile, get_profiles_file
from dbt_ci.utilities.multi_threading import run_multithreaded

logger = logging.getLogger(__name__)

def bigquery_client(args: Namespace) -> bigquery.Client:
    """Create a BigQuery client using credentials from the dbt profiles.yml file."""
    dbt_project_dir = getattr(args, "dbt_project_dir", None)
    if dbt_project_dir is None:
        raise ValueError("dbt_project_dir argument is required to initialize BigQuery client")

    dbt_profile = get_profiles_file(
        dbt_project_dir=dbt_project_dir,
        profiles_dir=getattr(args, "profiles_dir", None)
    )
    
    # Get the profile name from the project config
    profile_name = getattr(args, "project", {}).get("profile")
    
    if not profile_name:
        raise ValueError(
            "No 'profile' key found in dbt_project.yml")
    
    profile_config = dbt_profile.get(profile_name, {})
    
    if not profile_config:
        raise ValueError(
            f"Profile '{profile_name}' not found in profiles.yml")

    output = profile_config.get("outputs", {}).get(getattr(args, "target", None), {})
    if not output:
        raise ValueError(
            f"No output configuration found for target '{getattr(args, 'target', None)}' in profiles.yml")
    elif output.get("type") != "bigquery":
        raise ValueError(
            f"Output type for target '{getattr(args, 'target', None)}' is not 'bigquery' in profiles.yml")
    elif output.get("project") is None:
        raise ValueError(
            f"No 'project' specified for target '{getattr(args, 'target', None)}' in profiles.yml")
    elif output.get("location") is None:
        raise ValueError(
            f"No 'location' specified for target '{getattr(args, 'target', None)}' in profiles.yml")

    client = bigquery.Client(
        project=output.get("project", ""),
        location=output.get("location", "")
    )

    return client


def bigquery_query(client: bigquery.Client, query: str):
    """Execute a BigQuery query and return the results <add value>."""
    query_job = client.query(query)
    results = query_job.result()

    if query_job.errors:
        raise RuntimeError(
            f"BigQuery query failed with errors: {query_job.errors}")
    else:
        return results.job_id


def bigquery_ephemeral_strategy(
    ephemeral_map: dict[str, EphemeralMapNode],
    args: Namespace
) -> None:
    """Strategy for handling ephemeral run towards BigQuery."""
    def get_full_config(config: EphemeralMapNode | None) -> tuple[str | None, str | None, str | None]:
        """Extract (database, schema, name) from a config dict."""
        if config is None:
            return None, None, None
        return config.get("database"), config.get("schema"), config.get("name")

    # In BigQuery, ephemeral models can be materialized as temporary tables or CTEs.
    # For this implementation, we will materialize them as CTEs to avoid unnecessary storage costs.
    try:
        client = bigquery_client(args)
        profile = get_profile(args)
        threads = profile.get("threads", 5)

        datasets_to_create: set[str] = set()
        # Stored as {node_name: {"ephemeral_table_id": str, "reference_table_id": str }}
        clone_map: dict[str, dict[str, str]] = {}
        for node_metadata in ephemeral_map.values():
            if node_metadata["ephemeral_config"] is None or node_metadata["reference_config"] is None:
                logger.info(
                    f"Skipping node '{node_metadata['name']}' since it does not have both ephemeral and reference configurations.")
                continue
            ephemeral_database, ephemeral_schema, ephemeral_table = get_full_config(
                node_metadata["ephemeral_config"])
            reference_database, reference_schema, reference_table = get_full_config(
                node_metadata["reference_config"])
            dataset_id = f"{ephemeral_database}.{ephemeral_schema}"

            target_table_id = f"{ephemeral_database}.{ephemeral_schema}.{ephemeral_table}"
            reference_table_id = f"{reference_database}.{reference_schema}.{reference_table}"

            if target_table_id != reference_table_id:
                datasets_to_create.add(dataset_id)
                clone_map[node_metadata["name"]] = {
                    "ephemeral_table_id": f"{ephemeral_database}.{ephemeral_schema}.{ephemeral_table}",
                    "reference_table_id": f"{reference_database}.{reference_schema}.{reference_table}"
                }

        logger.info("Running ephemeral strategy for BigQuery...")
        bigquery_create_datasets(client, datasets_to_create, dry_run=False, threads=threads)
        clone_tables(client, clone_map, threads)
        return
    except Exception as e:
        raise RuntimeError(f"Error in BigQuery ephemeral strategy: {e}")

def create_ephemeral_datasets(
    client: bigquery.Client,
    datasets_to_create: set[str],
    threads: int = 5
) -> None:
    """Create ephemeral datasets in BigQuery if needed."""
    # This function can be used to create temporary datasets for ephemeral models if we choose to materialize them as tables instead of CTEs.
    if len(datasets_to_create) == 0:
        logger.info("No ephemeral datasets to create. Exiting ephemeral strategy.")
        return
    logger.info("Creating ephemeral datasets in BigQuery:")
    for dataset_id in datasets_to_create:
        logger.info(f"\n  - {dataset_id}")

    # Pass to multi_thread module
    func_list = [
        lambda dataset_id=dataset_id: create_dataset(client, dataset_id)
        for dataset_id in datasets_to_create
    ]
    run_multithreaded(
        func_list=func_list,
        threads=threads,
        exit_on_exception=True
    )

def bigquery_create_datasets(
    client: bigquery.Client,
    datasets_to_create: set[str],
    dry_run: bool = False,
    threads: int = 5
) -> None:
    """Create datasets in BigQuery."""
    if len(datasets_to_create) == 0:
        logger.info("No datasets to create. Exiting dataset creation step.")
        return
    logger.info("Creating datasets in BigQuery:")
    for dataset_id in datasets_to_create:
        logger.info(f"\n  - {dataset_id}")

    if dry_run:
        logger.info("\nDry run mode enabled - no datasets will actually be created.")
        return

    # Pass to multi_thread module
    func_list = [
        lambda dataset_id=dataset_id: create_dataset(client, dataset_id)
        for dataset_id in datasets_to_create
    ]
    run_multithreaded(
        func_list=func_list,
        threads=threads,
        exit_on_exception=True
    )

def create_dataset(client: bigquery.Client, dataset_id: str) -> None:
    """Create a BigQuery dataset if it does not already exist."""
    dataset = bigquery.Dataset(dataset_id)
    dataset.location = client.location
    try:
        result = client.create_dataset(dataset, exists_ok=True)
        if result.created:
            logger.info(f"Dataset '{dataset_id}' created successfully.")
        else:
            logger.info(f"Dataset '{dataset_id}' already exists.")
    except Exception as e:
        raise RuntimeError(f"Failed to create dataset '{dataset_id}': {e}")

def bigquery_delete_datasets(
    client: bigquery.Client,
    datasets_to_delete: set[str],
    dry_run: bool = False,
    threads: int = 5
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
    run_multithreaded(
        func_list=func_list,
        threads=threads,
        exit_on_exception=True
    )

def delete_dataset(client: bigquery.Client, dataset_id: str) -> None:
    """Delete a BigQuery dataset."""
    try:
        client.delete_dataset(dataset_id, delete_contents=True, not_found_ok=True)
        logger.info(f"Dataset '{dataset_id}' deleted successfully.")
    except Exception as e:
        raise RuntimeError(f"Failed to delete dataset '{dataset_id}': {e}")

def clone_tables(
    client: bigquery.Client,
    clone_map: dict[str, dict[str, str]],
    threads: int = 5
) -> None:
    """Clone reference tables to ephemeral tables in BigQuery."""
    logger.info("Cloning reference tables to ephemeral tables in BigQuery:")
    for node_name, table_ids in clone_map.items():
        logger.info(
            f"\n  - Cloning '{table_ids['reference_table_id']}' to '{table_ids['ephemeral_table_id']}' for node '{node_name}'")

    func_list = [
        lambda table_ids=table_ids: bigquery_query(client=client, 
        query=f"""
            CREATE OR REPLACE TABLE `{table_ids['ephemeral_table_id']}`
            CLONE `{table_ids['reference_table_id']}`
            """
        )
        for table_ids in clone_map.values()
    ]
    run_multithreaded(
        func_list=func_list,
        threads=threads,
        exit_on_exception=True
    )


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
                tables_to_delete.add(f"{table_id}__dbt_tmp")  # Also delete the dbt temporary table if it exists

        bigquery_delete_tables(client, tables_to_delete, getattr(args, "dry_run", False), threads)
    except Exception as e:
        raise RuntimeError(f"Error in BigQuery delete strategy: {e}")

def bigquery_delete_tables(
    client: bigquery.Client,
    tables_to_delete: set[str],
    dry_run: bool = False,
    threads: int = 5
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

    func_list = [
        lambda table_id=table_id: _delete_table(table_id)
        for table_id in tables_to_delete
    ]
    run_multithreaded(
        func_list=func_list,
        threads=threads,
        exit_on_exception=True
    )

def delete_table(table_id: str, args: Namespace) -> None:
    """
    Delete a single BigQuery table and its dbt temporary table.

    Args:
        table_id: Full table identifier (project.dataset.table)
        args: Namespace with dbt configuration (used to get BigQuery client)

    Returns:
        None

    Note:
        This function is designed to be called in parallel via multithreading.
        Each invocation deletes one table independently.
    """
    client = bigquery_client(args)

    try:
        client.delete_table(table_id, not_found_ok=True)
        logger.info(f"Deleted {table_id} from BigQuery")
    except Exception as e:
        logger.error(f"Error deleting {table_id} from BigQuery: {e}")
        raise


def bigquery_migration_strategy(migration_map: MigrationMap, args: Namespace) -> None:
    """Strategy for handling partitioning migrations towards BigQuery."""
    try:
        client = bigquery_client(args)
        profile = get_profile(args)
        if profile is None:
            raise ValueError("No profile found for the specified target. Please check your profiles.yml configuration.")

        threads: int = cast(int, profile.get("threads", 5))
        nodes = migration_map["nodes"]
        
        def migrate_table(node_data: dict) -> None:
            """Migrate a single table's partitioning by recreating it. Steps must run sequentially."""
            table_id: str = node_data["table_id"]
            table_name: str = table_id.split(".")[-1]  # RENAME TO only accepts a bare table name, not a fully-qualified path
            temp_table_id: str = f"{table_id}_temp_new_partition"
            dbt_tmp_table_id: str = f"{table_id}__dbt_tmp"
            partitioning_clause: str = render_bigquery_partition_clause(node_data["new_partitioning"])
            steps: list[str] = [
                # Step 1: Copy data into a new temp table with the new partitioning spec.
                # Using a new table name avoids the "cannot replace with different partitioning spec" error.
                f"CREATE OR REPLACE TABLE `{temp_table_id}` {partitioning_clause} AS SELECT * FROM `{table_id}`",
                # Step 2: Drop the original table (with its old partition spec).
                f"DROP TABLE IF EXISTS `{table_id}`",
                # Step 3: Rename the temp table to the original table name.
                # BigQuery RENAME TO only accepts a bare table name (no project/dataset prefix).
                f"ALTER TABLE `{temp_table_id}` RENAME TO `{table_name}`",
                # Step 4: Clean up any leftover dbt tmp table.
                f"DROP TABLE IF EXISTS `{dbt_tmp_table_id}`",
            ]
            for step in steps:
                client.query(step).result()
            logger.info(f"Migrated partitioning for table '{table_id}'")

        if args.dry_run:
            logger.info("Dry run mode enabled - no changes will be applied.")
            return

        # Each table's steps must run sequentially, but different tables can run in parallel.
        run_multithreaded(
            func_list=[
                lambda node_data=node_data: migrate_table(node_data)
                for node_data in nodes.values()
            ],
            threads=threads,
            exit_on_exception=True
        )
    except Exception as e:
        raise RuntimeError(f"An error occurred while initializing BigQuery client or processing migration map: {e}")


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
            raise ValueError("partition_by.range.start/end/interval required for int64 partitioning")

        return (
            "PARTITION BY "
            f"range_bucket({field}, generate_array({start}, {end}, {interval}))"
        )

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

    raise ValueError("Unsupported partitioning configuration. No PARTITION BY clause will be applied.")

def bigquery_create_tables(
    client: bigquery.Client,
    tables_to_create: set[str],
    dry_run: bool = False,
    threads: int = 5
) -> None:
    """Create tables in BigQuery."""
    if len(tables_to_create) == 0:
        logger.info("No tables to create. Exiting table creation step.")
        return
    logger.info("Creating tables in BigQuery:")
    for table_id in tables_to_create:
        logger.info(f"\n  - {table_id}")

    if dry_run:
        logger.info("\nDry run mode enabled - no tables will actually be created.")
        return

    func_list = [
        lambda table_id=table_id: create_table(client, table_id)
        for table_id in tables_to_create
    ]
    run_multithreaded(
        func_list=func_list,
        threads=threads,
        exit_on_exception=True
    )

def create_table(client: bigquery.Client, table_id: str) -> None:
    """Create a BigQuery table."""
    # This function can be implemented to create a single table in BigQuery if needed for the create strategy.
    try:
        table = bigquery.Table(table_id)
        client.create_table(table, exists_ok=True)
        logger.info(f"Table '{table_id}' created successfully.")
    except Exception as e:
        raise RuntimeError(f"Failed to create table '{table_id}': {e}")