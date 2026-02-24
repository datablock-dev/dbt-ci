"""BigQuery connector for dbt CI."""
import sys
import logging
from argparse import Namespace
from typing import Any, Dict, Set, Tuple
import click
from google.cloud import bigquery
from src.schema import DeleteMapNode, EphemeralMapNode, MigrationMap
from src.utilities.paths import get_profile, get_profiles_file
from src.utilities.multi_threading import run_multithreaded

logger = logging.getLogger(__name__)

def bigquery_client(args: Namespace) -> bigquery.Client:
    """Create a BigQuery client using credentials from the dbt profiles.yml file."""
    dbt_profile = get_profiles_file(
        dbt_project_dir=getattr(args, "dbt_project_dir", None),
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
        threads = args.target_config.get("threads", 5)

        datasets_to_create: Set[str] = set()
        # Stored as {node_name: {"ephemeral_table_id": str, "reference_table_id": str }}
        clone_map: dict[str, dict[str, str]] = {}
        for node_metadata in ephemeral_map.values():
            if node_metadata["ephemeral_config"] is None or node_metadata["reference_config"] is None:
                click.echo(
                    f"Skipping node '{node_metadata['name']}' since it does not have both ephemeral and reference configurations.")
                continue
            ephemeral_database, ephemeral_schema, ephemeral_table = get_full_config(
                node_metadata["ephemeral_config"])
            reference_database, reference_schema, reference_table = get_full_config(
                node_metadata["reference_config"])
            dataset_id = f"{ephemeral_database}.{ephemeral_schema}"
            datasets_to_create.add(dataset_id)
            clone_map[node_metadata["name"]] = {
                "ephemeral_table_id": f"{ephemeral_database}.{ephemeral_schema}.{ephemeral_table}",
                "reference_table_id": f"{reference_database}.{reference_schema}.{reference_table}"
            }

        click.echo("Running ephemeral strategy for BigQuery...")
        create_ephemeral_datasets(client, datasets_to_create, threads)
        clone_tables(client, clone_map, threads)
        return
    except Exception as e:
        raise RuntimeError(f"Error in BigQuery ephemeral strategy: {e}")


def create_ephemeral_datasets(
    client: bigquery.Client,
    datasets_to_create: Set[str],
    threads: int = 5
) -> None:
    """Create ephemeral datasets in BigQuery if needed."""
    # This function can be used to create temporary datasets for ephemeral models if we choose to materialize them as tables instead of CTEs.
    if len(datasets_to_create) == 0:
        click.echo("No ephemeral datasets to create. Exiting ephemeral strategy.")
        sys.exit(0)
    click.echo("Creating ephemeral datasets in BigQuery:")
    for dataset_id in datasets_to_create:
        click.echo(f"\n  - {dataset_id}")

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
            click.echo(f"Dataset '{dataset_id}' created successfully.")
        else:
            click.echo(f"Dataset '{dataset_id}' already exists.")
    except Exception as e:
        raise RuntimeError(f"Failed to create dataset '{dataset_id}': {e}")


def clone_tables(
    client: bigquery.Client,
    clone_map: dict[str, dict[str, str]],
    threads: int = 5
) -> None:
    """Clone reference tables to ephemeral tables in BigQuery."""
    click.echo("Cloning reference tables to ephemeral tables in BigQuery:")
    for node_name, table_ids in clone_map.items():
        click.echo(
            f"\n  - Cloning '{table_ids['reference_table_id']}' to '{table_ids['ephemeral_table_id']}' for node '{node_name}'")

    func_list = [
        lambda table_ids=table_ids: bigquery_query(client=client, 
        query=f"""
            CREATE OR REPLACE TABLE `{table_ids['ephemeral_table_id']} 
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
    client = bigquery_client(args)

    def _delete(table_id: str) -> None:
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
        tmp_table_id = f"{table_id}__dbt_tmp"

        try:
            client.delete_table(table_id, not_found_ok=True)
            client.delete_table(tmp_table_id, not_found_ok=True)
            click.echo(f"Deleted {table_id} from BigQuery")
        except Exception as e:
            click.echo(
                f"Error deleting {table_id} from BigQuery: {e}", err=True)
            raise

    # For BigQuery, we will delete tables directly using the BigQuery client.
    # This function can be expanded to handle any pre-deletion logic if needed.
    try:
        threads = args.target_config.get("threads", 5)
        funct_list = [
            lambda node_id=node_id, node_info=node_info: _delete(
                node_info["table_id"])
            for node_id, node_info in delete_map.items()
        ]

        run_multithreaded(
            func_list=funct_list,
            threads=threads,
            exit_on_exception=True
        )
    except Exception as e:
        logger.error(f"Error in BigQuery delete strategy: {e}")
        sys.exit(1)


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
        click.echo(f"Deleted {table_id} from BigQuery")
    except Exception as e:
        click.echo(f"Error deleting {table_id} from BigQuery: {e}", err=True)
        raise


def bigquery_migration_strategy(migration_map: MigrationMap, args: Namespace) -> None:
    """Strategy for handling partitioning migrations towards BigQuery."""
    try:
        client = bigquery_client(args)
        profile = get_profile(args)
        if profile is None:
            print("No profile found for the specified target. Please check your profiles.yml configuration.")
            sys.exit(1)

        threads: int = profile.get("threads", 5)
        nodes = migration_map["nodes"]
        queries = []

        for node_data in nodes.values():
            table_id = node_data["table_id"]
            temp_table_id = f"{table_id}_temp_new_partition"
            dbt_tmp_table_id = f"{table_id}__dbt_tmp"
            partitioning_clause = render_bigquery_partition_clause(
                node_data["new_partitioning"])
            queries.append(f"""
                DROP TABLE IF EXISTS `{dbt_tmp_table_id}`;
            """)
            queries.append(f"""
                CREATE OR REPLACE TABLE `{temp_table_id}`
                {partitioning_clause}
                AS SELECT * FROM `{table_id}`
                """
            )

        if args.dry_run:
            click.echo("Dry run mode enabled - no changes will be applied.")
            sys.exit(0)

        # Run using multithreading to speed up the process if there are multiple tables
        run_multithreaded(
            func_list=[
                # Execute the query and wait for it to finish
                lambda query=query: client.query(query).result()
                for query in queries
            ],
            threads=threads,
            exit_on_exception=True
        )

    except Exception as e:
        print(e, "An error occurred while initializing BigQuery client or processing migration map")
        sys.exit(1)


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
    try:
        if not partition_by:
            return ""

        field = partition_by.get("field")
        data_type = (partition_by.get("data_type") or "").lower()
        granularity = (partition_by.get("granularity") or "day").lower()
        ingestion = partition_by.get("time_ingestion_partitioning", False)

        if not field:
            raise Exception("partition_by.field is required")

        if data_type not in {"timestamp", "datetime", "date", "int64"}:
            raise Exception("partition_by.data_type must be one of: timestamp|datetime|date|int64")

        # ------------------------------------------------------------------
        # Ingestion-time partitioning
        # ------------------------------------------------------------------
        if ingestion:
            if granularity not in {"hour", "day", "month", "year"}:
                raise Exception("Ingestion-time partitioning supports: hour|day|month|year")
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
                raise Exception("partition_by.range.start/end/interval required for int64 partitioning")
            
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

            raise Exception("Date partitioning supports: day|month|year")

        # ------------------------------------------------------------------
        # Timestamp / Datetime partitioning
        # ------------------------------------------------------------------
        if data_type in {"timestamp", "datetime"}:
            if granularity not in {"hour", "day", "month", "year"}:
                raise Exception("Timestamp/datetime partitioning supports: hour|day|month|year")

            trunc_fn = "timestamp_trunc" if data_type == "timestamp" else "datetime_trunc"
            return f"PARTITION BY {trunc_fn}({field}, {granularity})"

        print("Unsupported partitioning configuration. No PARTITION BY clause will be applied.")
        return sys.exit(1)
    except Exception as e:
        print(f"Error rendering BigQuery partition clause: {e}")
        sys.exit(1)