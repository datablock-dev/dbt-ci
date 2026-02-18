from argparse import Namespace
import os
from pathlib import Path
import sys
import yaml
import json
from src.schema import DBTManifest, DBTProfile

def get_dir_name_from_path(path: str) -> str:
    """Get the directory name from a given path."""
    if os.path.isdir(path):
        return os.path.basename(os.path.normpath(path))
    elif os.path.isfile(path):
        return os.path.basename(os.path.dirname(path))
    elif not os.path.exists(path):
        print(f"Path '{path}' does not exist.")
        sys.exit(1)

def get_manifest_file(dbt_project_dir: str) -> DBTManifest:
    """
    Get the path to the manifest.json file in the target directory.
    Raises a FileNotFoundError if the file does not exist.
    """

    file = os.path.join(dbt_project_dir, "target/manifest.json")
    if not os.path.isfile(file):
        print (f"manifest.json not found in {dbt_project_dir}")
        sys.exit(1)
    with open(file, 'r', encoding='utf-8') as f:
        item = json.load(f)
        if isinstance(item, DBTManifest):
            return item
        print(f"manifest.json at {file} does not conform to expected structure.")
        sys.exit(1)
    
def get_manifest_file_full_path(file_path: str) -> DBTManifest:
    """
    Get the manifest.json file from the specified path.
    Raises a FileNotFoundError if the file does not exist.
    Uses pydantic to confirm the structure of the manifest file.
    """
    if not os.path.isfile(file_path):
        print(f"manifest.json not found at {file_path}")
        sys.exit(1)
    with open(file_path, 'r', encoding='utf-8') as f:
        item = json.load(f)
        if isinstance(item, DBTManifest):
            return item
        print(f"manifest.json at {file_path} does not conform to expected structure.")
        sys.exit(1)

def get_reference_manifest_file(reference_state_dir: str) -> DBTManifest:
    """
    Get the reference manifest.json file from the state directory.
    Raises a FileNotFoundError if the file does not exist.
    """
    file = os.path.join(reference_state_dir, "manifest.json")
    if os.path.isfile(reference_state_dir):
        # If the provided reference_state_dir is actually a file, use it directly
        file = reference_state_dir

    if not os.path.isfile(file):
        print(f"manifest.json not found in {reference_state_dir}")
        sys.exit(1)
    with open(file, 'r', encoding='utf-8') as f:
        return json.load(f)

def get_dbt_project_file(dbt_project_dir: str) -> dict:
    """
    Get the path to the dbt_project.yml file in the specified directory.
    Raises a FileNotFoundError if the file does not exist.
    """
    file = os.path.join(dbt_project_dir, "dbt_project.yml")
    if not os.path.isfile(file):
        print(f"dbt_project.yml not found in {dbt_project_dir}")
        sys.exit(1)
    
    with open(file, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def get_profiles_file(dbt_project_dir: str, profiles_dir: str | None = None):
    """
    Get the path to the profiles.yml file in the specified directory or the default locations.
    Raises a FileNotFoundError if the file does not exist in any of the expected locations
    """
    if profiles_dir:
        file = os.path.join(profiles_dir, "profiles.yml")
        if not os.path.isfile(file):
            print(f"profiles.yml not found in {profiles_dir}")
            sys.exit(1)
        
        with open(file, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    else:
        # Check for profiles.yml in the dbt project directory
        file = os.path.join(dbt_project_dir, "profiles.yml")
        if os.path.isfile(file):
            with open(file, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        
        # Check for profiles.yml in the user's home directory
        home_dir = os.path.expanduser("~")
        file = os.path.join(home_dir, ".dbt/profiles.yml")
        if os.path.isfile(file):
            with open(file, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)

        print("profiles.yml not found in the specified profiles directory, dbt project directory, or ~/.dbt/")
        sys.exit(1)

def get_dbt_project_config(dbt_root_path: str) -> dict:
    """Get the DBT project configuration from the dbt_project.yml file.
    Raises a FileNotFoundError if the dbt_project.yml file does not exist in the specified directory.
    """
    dbt_project_path = get_dbt_project_path(dbt_root_path)
    if dbt_project_path is None:
        print("DBT project path could not be resolved.")
        sys.exit(1)
    dbt_project_path_yaml_path = os.path.join(dbt_project_path, "dbt_project.yml")
    if not os.path.exists(dbt_project_path_yaml_path):
        print(f"dbt_project.yml not found at {dbt_project_path_yaml_path}")
        sys.exit(1)
    with open(dbt_project_path_yaml_path, 'r', encoding='utf-8') as file:
        project_config = yaml.safe_load(file)

    return project_config

def get_dbt_project_path(dbt_project_path: str) -> Path:
    """
    Get the DBT project root directory path.

    Args:
        dbt_project_path: Path to the DBT project directory

    Returns:
        Path: Absolute path to DBT project directory
    """
    if not dbt_project_path:
        print("DBT project path not provided.")
        return sys.exit(1)

    project_path = Path(dbt_project_path)

    # Convert relative to absolute
    if not project_path.is_absolute():
        project_path = Path.cwd() / project_path

    return project_path.resolve()

def get_dbt_profiles_config(dbt_root_path: str):
    """Get the DBT profiles configuration from the profiles.yml file."""
    dbt_project_path = get_dbt_project_path(dbt_root_path)
    if dbt_project_path is None:
        print("DBT project path could not be resolved.")
        sys.exit(1)

    profiles_path = os.path.join(dbt_project_path, "profiles.yml")
    if not os.path.exists(profiles_path):
        print(f"profiles.yml not found at {profiles_path}")
        sys.exit(1)

    with open(profiles_path, 'r', encoding='utf-8') as file:
        profiles = yaml.safe_load(file)

    return profiles

def get_profile(args: Namespace) -> DBTProfile:
    """Get the DBT profile output configuration based on the provided arguments."""
    dbt_root_path = getattr(args, "dbt_project_dir", None)
    if dbt_root_path is None:
        print("DBT project path not specified in arguments. Please pass the path using --dbt-project-dir <path>.")
        sys.exit(1)

    dbt_project_file = get_dbt_project_config(dbt_root_path)
    profiles = get_dbt_profiles_config(dbt_root_path)
    dbt_profile = dbt_project_file.get("profile", None)
    target = getattr(args, "target", None) or profiles.get(dbt_profile, {}).get("target", None)
    profile_name = getattr(args, "profile", "default")
    print(target)

    if target is None:
        print("Target environment not specified in arguments.")
        print("Defaulting to ")
        sys.exit(1)
    
    # Get the default profile (assuming 'default' is the profile name)
    if profile_name not in profiles:
        print(f"Profile '{profile_name}' not found in profiles.yml")
        sys.exit(1)
    
    profile = profiles[profile_name]
    
    # Get the output configuration for the target
    if "outputs" not in profile or target not in profile["outputs"]:
        print(f"Target '{target}' not found in profile '{profile_name}'")
        sys.exit(1)
    
    output_config: DBTProfile = profile["outputs"][target]

    return output_config

def get_absolute_path(path: str) -> str:
    """Return an absolute version of the given path."""
    return str(Path(path).resolve())
