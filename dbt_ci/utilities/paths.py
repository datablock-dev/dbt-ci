import logging
import os
import tempfile
import yaml
import json
from pathlib import Path
from argparse import Namespace
from typing import cast
from dbt_ci.errors import ConfigurationError
from dbt_ci.schema import DBTManifest, DBTProfile

logger = logging.getLogger(__name__)


def get_cache_dir() -> Path:
    """
    Return the directory holding dbt-ci's cache and log files.

    Defaults to '<temp dir>/dbt-ci'. Set DBT_CI_CACHE_DIR to relocate it, which is what
    concurrent CI jobs sharing a runner need so they don't overwrite each other's state.
    """
    override = os.environ.get("DBT_CI_CACHE_DIR")
    if override:
        return Path(override)
    return Path(tempfile.gettempdir()) / "dbt-ci"


def get_manifest_file(dbt_project_dir: str) -> DBTManifest:
    """
    Get the path to the manifest.json file in the target directory.
    Raises a FileNotFoundError if the file does not exist.
    """

    file = os.path.join(dbt_project_dir, "target/manifest.json")
    if not os.path.isfile(file):
        raise FileNotFoundError(f"manifest.json not found in {dbt_project_dir}")
    with open(file, "r", encoding="utf-8") as f:
        return json.load(f)


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
        raise FileNotFoundError(f"manifest.json not found in {reference_state_dir}")
    with open(file, "r", encoding="utf-8") as f:
        return json.load(f)


def get_dbt_project_config(dbt_root_path: str) -> dict:
    """Return the parsed dbt_project.yml of the project at the given path."""
    project_file = get_dbt_project_path(dbt_root_path) / "dbt_project.yml"
    if not project_file.is_file():
        raise ConfigurationError(f"dbt_project.yml not found at {project_file}")
    with open(project_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_dbt_project_path(dbt_project_path: str) -> Path:
    """Return the absolute path of the dbt project directory."""
    if not dbt_project_path:
        raise ConfigurationError("DBT project path not provided.")
    return Path(dbt_project_path).resolve()


def get_profiles_file(dbt_project_dir: str, profiles_dir: str | None = None) -> dict:
    """
    Return the parsed profiles.yml, found where dbt itself would find it.

    An explicit profiles directory (--profiles-dir or DBT_PROFILES_DIR) is the only place
    looked in. Otherwise the project directory comes first, then dbt's own defaults: the
    working directory and ~/.dbt.
    """
    if profiles_dir:
        directories = [Path(profiles_dir)]
    else:
        directories = [Path(dbt_project_dir), Path.cwd(), Path.home() / ".dbt"]

    for directory in directories:
        file = directory / "profiles.yml"
        if file.is_file():
            with open(file, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}

    searched = ", ".join(str(directory) for directory in dict.fromkeys(directories))
    raise ConfigurationError(f"profiles.yml not found in {searched}")


def get_profile(args: Namespace) -> DBTProfile:
    """
    Return the profiles.yml output for the configured target.

    The profile is the one dbt_project.yml names, and the target is --target or the
    profile's default target.
    """
    dbt_root_path = getattr(args, "dbt_project_dir", None)
    if dbt_root_path is None:
        raise ConfigurationError(
            "DBT project path not specified in arguments. Please pass the path using "
            "--dbt-project-dir <path>."
        )

    profile_name = get_dbt_project_config(dbt_root_path).get("profile") or "default"
    profiles = get_profiles_file(dbt_root_path, getattr(args, "profiles_dir", None))
    profile = profiles.get(profile_name)
    if not isinstance(profile, dict):
        raise ConfigurationError(f"Profile '{profile_name}' not found in profiles.yml")

    target = getattr(args, "target", None) or profile.get("target")
    if target is None:
        raise ConfigurationError(
            f"No target given and profile '{profile_name}' sets no default target. "
            "Please pass the target using --target <target>."
        )

    outputs = profile.get("outputs") or {}
    if target not in outputs:
        raise ConfigurationError(f"Target '{target}' not found in profile '{profile_name}'")

    return cast(DBTProfile, outputs[target])


def get_absolute_path(path: str) -> str:
    """Return an absolute version of the given path."""
    return str(Path(path).resolve())
