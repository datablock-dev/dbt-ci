"""
    Module to manage mapping of environment variables and command-line flags for dbt configuration.
    This module defines a Variables class that creates mappings between environment variables and dbt command-line flags.
    The class includes mappings for:
    - State file paths (production and reference)
    - dbt project directory
    - dbt profiles directory
    - dbt target
    - dbt variables
    - dbt runner type
    - dbt entrypoint
    - Dry run flag
    - Logging level
"""
import os
from argparse import Namespace
from typing import List, Dict, Tuple

class Variables:
    """Class to manage mapping of environment variables and command-line flags."""
    def __init__(self, args: Namespace):
        self.args = args
        self.state_file = self.create_map_dict(
            envs=["DBT_STATE_FILE", "STATE_FILE"],
            flags=["prod_manifest_dir", "reference_manifest_dir", "state"]
        )
        self.dbt_project_dir = self.create_map_dict(
            envs=["DBT_PROJECT_DIR"],
            flags=["dbt_project_dir"]
        )
        self.dbt_profiles_dir = self.create_map_dict(
            envs=["DBT_PROFILES_DIR"],
            flags=["profiles_dir"]
        )
        self.dbt_target = self.create_map_dict(
            envs=["DBT_TARGET", "TARGET"],
            flags=["target"]
        )
        self.dbt_vars = self.create_map_dict(
            envs=["DBT_VARS", "VARS"],
            flags=["vars"]
        )
        self.dbt_runner = self.create_map_dict(
            envs=["DBT_RUNNER", "RUNNER"],
            flags=["runner"]
        )
        self.dbt_entrypoint = self.create_map_dict(
            envs=["DBT_ENTRYPOINT", "ENTRYPOINT"],
            flags=["entrypoint"]
        )
        self.dry_run = self.create_map_dict(
            envs=["DBT_DRY_RUN", "DRY_RUN"],
            flags=["dry_run"]
        )
        self.log_level = self.create_map_dict(
            envs=["DBT_LOG_LEVEL", "LOG_LEVEL"],
            flags=["log_level"]
        )

    def create_map_dict(
        self, 
        envs: List[str],
        flags: List[str]
    ) -> Tuple[str | None, Dict[str, List[str]]]:
        """Create a mapping dictionary from environment variables to dbt flags."""
        mapping = {
            "env": envs,
            "flag": flags
        }

        # Resolve variable value from environment variables or command-line flags
        # The order of precedence is: command-line flags > environment variables > default values
        value = None
        for flag in flags:
            if hasattr(self.args, flag) and getattr(self.args, flag) is not None:
                value = getattr(self.args, flag)
                break
        else:
            for env in envs:
                if env in os.environ and os.environ[env] != "":
                    value = os.environ[env]
                    break

        return value, mapping