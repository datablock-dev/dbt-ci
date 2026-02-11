"""BigQuery connector for dbt CI."""
import sys
import logging
from argparse import Namespace
from typing import Dict, Set, Tuple
import click
from google.cloud import bigquery
from src.utilities.paths import get_profiles_file
from src.schema import DeleteMapNode, DependencyGraphNode, EphemeralMapNode, MigrationMap
from src.utilities.multi_threading import run_multithreaded

logger = logging.getLogger(__name__)

def bigquery_client(variables: Namespace) -> bigquery.Client:
    """Create a BigQuery client using credentials from the dbt profiles.yml file."""
    dbt_profile = get_profiles_file(
        dbt_project_dir=variables.dbt_project_dir,
        profiles_dir=variables.profiles_dir
    )

    output = dbt_profile.get("outputs", {}).get(variables.target, {})
    if not output:
        raise ValueError(f"No output configuration found for target '{variables.target}' in profiles.yml")
    elif output.get("type") != "bigquery":
        raise ValueError(f"Output type for target '{variables.target}' is not 'bigquery' in profiles.yml")
    elif output.get("project") is None:
        raise ValueError(f"No 'project' specified for target '{variables.target}' in profiles.yml")
    elif output.get("location") is None:
        raise ValueError(f"No 'location' specified for target '{variables.target}' in profiles.yml")

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
        raise RuntimeError(f"BigQuery query failed with errors: {query_job.errors}")
    else:
        return results.job_id

def bigquery_ephemeral_strategy(
    ephemeral_map: Dict[str, EphemeralMapNode],
    variables: Namespace
) -> None:
    """Strategy for handling ephemeral run towards BigQuery."""
    def get_full_config(config: EphemeralMapNode | None) -> Tuple[str | None, str | None, str | None]:
        """Extract (database, schema, name) from a config dict."""
        if config is None:
            return None, None, None
        return config.get("database"), config.get("schema"), config.get("name")

    # In BigQuery, ephemeral models can be materialized as temporary tables or CTEs.
    # For this implementation, we will materialize them as CTEs to avoid unnecessary storage costs.
    try:
        client = bigquery_client(variables)
        threads = variables.target_config.get("threads", 5)

        datasets_to_create: Set[str] = set()
        clone_map: Dict[str, Dict[str, str]] = {} # Stored as {node_name: {"ephemeral_table_id": str, "reference_table_id": str }}
        for node_metadata in ephemeral_map.values():
            if node_metadata["ephemeral_config"] is None or node_metadata["reference_config"] is None:
                click.echo(f"Skipping node '{node_metadata['name']}' since it does not have both ephemeral and reference configurations.")
                continue
            ephemeral_database, ephemeral_schema, ephemeral_table = get_full_config(node_metadata["ephemeral_config"])
            reference_database, reference_schema, reference_table = get_full_config(node_metadata["reference_config"])
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
    clone_map: Dict[str, Dict[str, str]],
    threads: int = 5
) -> None:
    """Clone reference tables to ephemeral tables in BigQuery."""
    click.echo("Cloning reference tables to ephemeral tables in BigQuery:")
    for node_name, table_ids in clone_map.items():
        click.echo(f"\n  - Cloning '{table_ids['reference_table_id']}' to '{table_ids['ephemeral_table_id']}' for node '{node_name}'")

    query = f"""
    CREATE OR REPLACE TABLE `{table_ids['ephemeral_table_id']} 
    CLONE `{table_ids['reference_table_id']}`
    """

    func_list = [
        lambda table_ids=table_ids: bigquery_query(client, query)
        for table_ids in clone_map.values()
    ]
    run_multithreaded(
        func_list=func_list,
        threads=threads,
        exit_on_exception=True
    )

def bigquery_delete_table(
    delete_map: Dict[str, DeleteMapNode],
    variables: Namespace
):
    """Strategy for handling deletions towards BigQuery."""
    try:
        client = bigquery_client(variables)
        threads = variables.variables.target_config.get("threads", 5)
        # Delete through multi-threading
        func_list = [
            lambda table_id=node_data["table_id"]: bigquery_query(client, f"DROP TABLE IF EXISTS `{table_id}`")
            for node_data in delete_map.values()
        ]
        run_multithreaded(
            func_list=func_list,
            threads=threads,
            exit_on_exception=True
        )

        return
    except Exception as e:
        raise RuntimeError(f"Error in BigQuery delete strategy: {e}")
 
def change_partitioning(
    migration_map: MigrationMap,
    args: Namespace
) -> Dict[str, bool]:
    """
    Change partitioning configuration for BigQuery tables by recreating them.

    Unlike clustering changes, partitioning changes require full table recreation because
    partitioning is defined at table creation time and cannot be modified in-place.

    This function handles three scenarios:
    1. Adding partitioning to a non-partitioned table
    2. Changing partitioning configuration (field, granularity, or data type)
    3. Removing partitioning from a partitioned table

    Process:
    1. Create temporary table with new partitioning scheme using CREATE TABLE AS SELECT
    2. Copy all data from original table to temporary table
    3. Delete original table
    4. Rename temporary table to original table name

    Partition Expression Logic (Critical for BigQuery compatibility):
    - DATE column + DAY granularity: Use column directly (e.g., PARTITION BY event_date)
    - DATE column + MONTH/YEAR: Use DATE_TRUNC(column, granularity)
    - DATETIME/TIMESTAMP + DAY: Use DATE(column) for efficient date partitions
    - DATETIME/TIMESTAMP + HOUR/MONTH/YEAR: Use DATETIME_TRUNC/TIMESTAMP_TRUNC

    Args:
        migration_map: MigrationMap containing connector type and nodes with partitioning changes.
            Each node contains:
                - table_id: Full table identifier (project.dataset.table)
                - old_partitioning: Previous partition config or None
                - new_partitioning: New partition config (field, granularity, data_type) or None to remove
        args: Namespace containing command-line arguments (used to get BigQuery client)

    Returns:
        Dict mapping node_id to success status (True if successful, False if failed)

    Example:
        - Adding partitioning: old_partitioning=None, new_partitioning={"field": "date", "granularity": "DAY", "data_type": "DATE"}
        - Removing partitioning: old_partitioning={...}, new_partitioning=None
        - Changing field: old_partitioning={"field": "timestamp"}, new_partitioning={"field": "date"}

    Note:
        This operation is resource-intensive and requires temporary storage equal to
        the original table size. Plan accordingly for large tables.
    """

    # Initialize BigQuery client with specified GCP project
    client = bigquery_client(args)
    nodes = migration_map["nodes"]
    results: Dict[str, bool] = {}

    for node_id, node_data in nodes.items():
        table_id = node_data["table_id"]
        temp_table_id = f"{table_id}_temp_new_partition"
        dbt_tmp_table_id = f"{table_id}__dbt_tmp"
        partition_info = node_data["new_partitioning"]

        try:
            # Handle two scenarios:
            # 1. Adding/changing partitioning (partition_info is a dict)
            # 2. Removing partitioning (partition_info is None)
            
            if partition_info is None:
                # Case: Remove partitioning - recreate as non-partitioned table
                logger.info(f"Removing partitioning for table: {table_id}")
                partition_clause = ""
            else:
                # Case: Add or change partitioning
                partition_field = partition_info["field"]
                granularity = partition_info["granularity"]
                data_type = partition_info.get("data_type", "TIMESTAMP")

                # Build partition expression based on column data type and granularity
                # BigQuery has strict requirements for partition expressions:
                #
                # For DATE columns:
                #   - DAY granularity: Use column directly (no function wrapper)
                #     Example: PARTITION BY event_date
                #   - MONTH/YEAR: Use DATE_TRUNC function
                #     Example: PARTITION BY DATE_TRUNC(event_date, MONTH)
                #
                # For DATETIME/TIMESTAMP columns with DAY granularity:
                #   - Best practice: Use DATE() to create date-partitioned tables
                #     Example: PARTITION BY DATE(event_time)
                #   - More efficient than DATETIME_TRUNC/TIMESTAMP_TRUNC for daily partitions
                #
                # For DATETIME/TIMESTAMP columns with HOUR/MONTH/YEAR:
                #   - Use DATETIME_TRUNC or TIMESTAMP_TRUNC
                #     Example: PARTITION BY TIMESTAMP_TRUNC(event_time, HOUR)

                # DATE column partitioning
                if data_type == "DATE" and granularity == "DAY":
                    partition_expression = partition_field
                elif data_type == "DATE" and granularity in ["MONTH", "YEAR"]:
                    partition_expression = f"DATE_TRUNC({partition_field}, {granularity})"
                # DATETIME column partitioning
                elif data_type == "DATETIME" and granularity == "DAY":
                    partition_expression = f"DATE({partition_field})"
                elif data_type == "DATETIME" and granularity in ["HOUR", "MONTH", "YEAR"]:
                    partition_expression = f"DATETIME_TRUNC({partition_field}, {granularity})"
                # TIMESTAMP column partitioning
                elif data_type == "TIMESTAMP" and granularity == "DAY":
                    partition_expression = f"DATE({partition_field})"
                elif data_type == "TIMESTAMP" and granularity in ["HOUR", "MONTH", "YEAR"]:
                    partition_expression = f"TIMESTAMP_TRUNC({partition_field}, {granularity})"
                else:
                    raise ValueError(
                        f"Unsupported combination: data_type='{data_type}', granularity='{granularity}'"
                    )
                
                partition_clause = f"PARTITION BY {partition_expression}"
                logger.info(f"Changing partitioning for table: {table_id}")
                logger.info(
                    f"  - New partition: {granularity} by field {partition_field} (type: {data_type})"
                )
                logger.info(f"  - Partition expression: {partition_expression}")

            # --- Step 1 & 2: Create temporary table with new partitioning and copy data ---
            # Uses CREATE OR REPLACE TABLE ... AS SELECT to:
            # 1. Define new partitioning scheme (or remove it if partition_clause is empty)
            # 2. Copy all data from original table in one operation
            create_query = f"""
                CREATE OR REPLACE TABLE `{temp_table_id}`
                {partition_clause}
                AS SELECT * FROM `{table_id}`;
            """
            # Execute the CREATE TABLE AS SELECT query
            # This creates the temp table with new/no partitioning and copies all data
            logger.info(f"  - Running CREATE TABLE AS SELECT to create '{temp_table_id}'...")
            client.query(create_query).result()  # .result() blocks until job completes

            # --- Step 3: Delete the original table ---
            # Remove old table to free up the table name for the new partitioned version
            logger.info(f"  - Dropping original table '{table_id}'...")
            client.delete_table(table_id, not_found_ok=True)

            # Also clean up dbt temporary table if it exists
            logger.info(f"  - Dropping DBT tmp table '{dbt_tmp_table_id}'...")
            client.delete_table(dbt_tmp_table_id, not_found_ok=True)

            # --- Step 4: Rename temporary table to original name ---
            # Use copy_table instead of rename to preserve all metadata
            logger.info(f"  - Copying '{temp_table_id}' to '{table_id}'...")
            job_config = bigquery.CopyJobConfig()
            job_config.write_disposition = "WRITE_TRUNCATE"  # Replace if exists
            job_config.create_disposition = (
                "CREATE_IF_NEEDED"  # Create if doesn't exist
            )
            client.copy_table(temp_table_id, table_id, job_config=job_config).result()

            # Clean up temporary table after successful copy
            client.delete_table(temp_table_id)

            logger.info(f"Successfully changed partitioning for {table_id}\n")
            results[node_id] = True
        except Exception as e:
            logger.error(f"Error changing partitioning for {table_id}: {e}")
            results[node_id] = False
            sys.exit(1)
    
    return results

def get_changed_partitioning(
    target_nodes: Dict[str, Dict[str, DependencyGraphNode]],
    reference_nodes: Dict[str, Dict[str, DependencyGraphNode]],
    connector: str = "bigquery"
) -> MigrationMap:
    migration_map: MigrationMap = {
        "connector": connector,
        "nodes": {}
    }

    for node_id, node_metadata in target_nodes.items():
        node_config = node_metadata.get("config", {})
        target_partitioning_config = node_config.get("partition_by", None)
        reference_partitioning_config = reference_nodes.get(node_id, {}).get("config", {}).get("partition_by", None)
        # Skip non-incremental models since partitioning changes only apply to incremental models in BigQuery
        if node_config.get("materialized", None) != "incremental":
            continue
        
        # Check if partitioning has been changed
        # Dict comparison is order-insensitive since Python 3.7+
        if target_partitioning_config != reference_partitioning_config:
            migration_map["nodes"][node_id] = {
                "table_id": f"{node_metadata.get('database', '')}.{node_metadata.get('schema', '')}.{node_metadata.get('name', '')}",
                "compiled_code": node_metadata.get("compiled_code", None),
                "old_partitioning": reference_partitioning_config,
                "new_partitioning": target_partitioning_config
            }

    return migration_map