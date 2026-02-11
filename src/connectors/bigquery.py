"""BigQuery connector for dbt CI."""
from argparse import Namespace
import sys
from typing import Dict, Set, Tuple
import click
from google.cloud import bigquery
from src.paths import get_profiles_file
from src.schema import DeleteMapNode, EphemeralMapNode
from src.utilities.multi_threading import run_multithreaded

def bigquery_client(args) -> bigquery.Client:
    """Create a BigQuery client using credentials from the dbt profiles.yml file."""
    dbt_profile = get_profiles_file(
        dbt_project_dir=args.dbt_project_dir,
        profiles_dir=args.profiles_dir
    )

    output = dbt_profile.get("outputs", {}).get(args.target, {})
    if not output:
        raise ValueError(f"No output configuration found for target '{args.target}' in profiles.yml")
    elif output.get("type") != "bigquery":
        raise ValueError(f"Output type for target '{args.target}' is not 'bigquery' in profiles.yml")
    elif output.get("project") is None:
        raise ValueError(f"No 'project' specified for target '{args.target}' in profiles.yml")
    elif output.get("location") is None:
        raise ValueError(f"No 'location' specified for target '{args.target}' in profiles.yml")

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
        threads = variables.variables.target_config.get("threads", 5)

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
        query = f""
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