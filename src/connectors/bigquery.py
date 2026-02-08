from google.cloud import bigquery
from src.paths import get_profiles_file

def bigquery_client(args) -> bigquery.Client:
    """Create a BigQuery client using credentials from the dbt profiles.yml file."""
    dbt_profile = get_profiles_file(
        dbt_project_dir=args.dbt_project_dir,
        profiles_dir=args.profiles_dir
    )

    output = dbt_profile.get("outputs", {}).get(args.target, {})
    if not output:
        raise ValueError(f"No output configuration found for target '{args.target}' in profiles.yml")

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