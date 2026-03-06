"""
Module for Git-related utilities, such as cloning repositories and managing branches.
"""
import os
import subprocess
from argparse import Namespace
from typing import Literal

class GitAdapter:
    # Not being utilised at the moment
    provider = os.getenv("GIT_PROVIDER", "github").lower()

    def __init__(self, args: Namespace):
        self.args = args
        head_branch = subprocess.run(["git", "remote", "show", "origin"], capture_output=True, text=True, check=True)
        head_branch = head_branch.stdout.splitlines()
        head_branch = [line for line in head_branch if "HEAD branch" in line][0].split(":")[-1].strip()
        self.head_branch = head_branch

        subprocess.run(["git", "fetch", "origin", head_branch], check=True)

        # Get the difference between the head branch and the current branch
        result = subprocess.run(
            ["git", "diff", "--name-status", f"origin/{head_branch}", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )

        # Return a list of tuples containing the change type and file path
        self.changes: list[list[str]] = [line.split("\t") for line in result.stdout.splitlines()]

    def get_changed_files(
        self, 
        extensions: list[Literal[".sql", ".yml", ".yaml", ".py"]] | None = None
    ) -> list[list[str]]:
        """Return a list of changed files with their change types."""
        dbt_project_dir: str | None = getattr(self.args, "dbt_project_dir", None)
        if dbt_project_dir is None:
            raise ValueError("DBT project directory not specified in arguments.")

        dbt_related_changes: list[list[str]] = []
        for change_type, file_path in self.changes:
            if file_path.startswith(dbt_project_dir):
                file_name = file_path.split("/")[-1]

                if extensions is None:
                    dbt_related_changes.append([change_type, file_name])
                elif any(file_name.endswith(ext) for ext in extensions):
                    dbt_related_changes.append([change_type, file_name])

        return dbt_related_changes