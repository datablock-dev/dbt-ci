import json
import sys
import logging
from pathlib import Path
from argparse import Namespace
from dbt_ci.schema import StorageConnectorConfig

logger = logging.getLogger(__name__)

def resolve_manifest_file_from_storage(
    resolved_storage: tuple[StorageConnectorConfig, str],
    args: Namespace
) -> Path:
    """Download manifest file from storage and save to local path for graph generation.
    
    Returns:
        Path: The local directory path where the manifest was saved
    """
    cwd = Path.cwd()
    storage_connector, state_uri = resolved_storage
    logger.info(f"Using storage connector '{storage_connector.get('name', 'Unknown')}' for state management with URI: {state_uri}")
    reference_manifest = storage_connector["download"](state_uri)
    dbtstate_dir: Path | None = None
    dbt_project_dir = getattr(args, "dbt_project_dir", None)
    reference_state = getattr(args, "reference_state", None)

    if dbt_project_dir is None:
        logger.error("No dbt_project_dir specified. Please provide the path to your DBT project using the --dbt-project-dir argument.")
        sys.exit(1)

    # Write and download manifest to path
    # When using Docker, always use the local dbt_project_dir/.dbtstate path on host
    if getattr(args, "runner", None) == "docker" or reference_state is None:
        dbtstate_dir = cwd / dbt_project_dir / ".dbtstate" # Default
    else:
        dbtstate_dir = cwd / reference_state

    if dbtstate_dir is None:
        logger.error("No valid path found for downloading manifest file. Please specify a valid --state path or ensure your dbt_project_dir is correct.")
        sys.exit(1)

    Path(dbtstate_dir).mkdir(parents=True, exist_ok=True)
    manifest_path = dbtstate_dir / "manifest.json"

    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(reference_manifest, indent=2))
    logger.info(f"Reference manifest successfully downloaded and saved to {manifest_path}")

    return dbtstate_dir