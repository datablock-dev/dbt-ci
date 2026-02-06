import os
import yaml
import json

def get_manifest_file(dbt_project_dir: str) -> dict:
    """
    Get the path to the manifest.json file in the target directory.
    Raises a FileNotFoundError if the file does not exist.
    """
    file = os.path.join(dbt_project_dir, "target/manifest.json")
    if not os.path.isfile(file):
        raise FileNotFoundError(f"manifest.json not found in {dbt_project_dir}/target")
    with open(file, 'r', encoding='utf-8') as f:
        return json.load(f)

def get_dbt_project_file(dbt_project_dir: str) -> dict:
    """
    Get the path to the dbt_project.yml file in the specified directory.
    Raises a FileNotFoundError if the file does not exist.
    """
    file = os.path.join(dbt_project_dir, "dbt_project.yml")
    if not os.path.isfile(file):
        raise FileNotFoundError(f"dbt_project.yml not found in {dbt_project_dir}")
    
    with open(file, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def get_profiles_file(
    dbt_project_dir: str,
    profiles_dir: str | None = None
):
    """
    Get the path to the profiles.yml file in the specified directory or the default locations.
    Raises a FileNotFoundError if the file does not exist in any of the expected locations
    """
    if profiles_dir:
        file = os.path.join(profiles_dir, "profiles.yml")
        if not os.path.isfile(file):
            raise FileNotFoundError(f"profiles.yml not found in {profiles_dir}")
        
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
        
        raise FileNotFoundError("profiles.yml not found in the specified profiles directory, dbt project directory, or ~/.dbt/")

