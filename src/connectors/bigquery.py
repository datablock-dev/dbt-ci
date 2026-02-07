from google.cloud import bigquery
from src.paths import get_profiles_file

def bigquery_client(args) -> bigquery.Client:
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
    query_job = client.query(query)
    results = query_job.result()
    return results.to_dataframe()