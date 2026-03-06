"""
Module for Git-related utilities, such as cloning repositories and managing branches.
"""
import os
import subprocess
from argparse import Namespace
from typing import Literal, cast

GIT_STATUS_MAPPING = {
    "M": "modified",
    "A": "added",
    "D": "deleted",
    "R": "renamed" # -> Is same as deleted?
}

type GitChangeType = Literal["modified", "added", "deleted", "renamed"]

class GitAdapter:
    # Not being utilised at the moment
    provider = os.getenv("GIT_PROVIDER", "github").lower()

    def __init__(self, args: Namespace):
        self.args = args
        head_branch = subprocess.run(
            ["git", "remote", "show", "origin"], 
            capture_output=True, 
            text=True, 
            check=True
        )
        head_branch = head_branch.stdout.splitlines()
        head_branch = [line for line in head_branch if "HEAD branch" in line][0].split(":")[-1].strip()
        self.head_branch = head_branch

        subprocess.run(["git", "fetch", "origin", head_branch], check=True)

        # Get the difference between the head branch and the current branch
        result = subprocess.run(
            ["git", "diff", "--name-status", f"origin/{head_branch}", "HEAD"],
            capture_output=True,
            text=True,
            check=True
        )

        # Return a list of tuples containing the change type and file path
        self.changes: list[list[str]] = [line.split("\t") for line in result.stdout.splitlines()]

    def get_changed_files(
        self,
        remove_extensions: bool = False,
        extensions: list[Literal[".sql", ".yml", ".yaml", ".py"]] | None = None
    ) -> dict[GitChangeType, list[str]]:
        """Return a list of changed files with their change types."""
        dbt_project_dir: str | None = getattr(self.args, "dbt_project_dir", None)
        if dbt_project_dir is None:
            print(f"ARGS: {self.args}")
            raise ValueError("DBT project directory not specified in arguments.")

        dbt_related_changes: dict[GitChangeType, list[str]] = {}
        for change in self.changes:
            change_type = change[0]
            change_type_key: GitChangeType | None = cast(GitChangeType | None, GIT_STATUS_MAPPING.get(change_type, None))
            if change_type_key is None:
                continue
            file_path = change[-1]  # For renames (R100\told\tnew), use the new path (last element)
            if dbt_project_dir in file_path:
                file_name = file_path.split(f"{dbt_project_dir}/")[-1]

                if extensions is None:
                    dbt_related_changes.setdefault(change_type_key, []).append(file_name)
                elif any(file_name.endswith(ext) for ext in extensions):
                    dbt_related_changes.setdefault(change_type_key, []).append(file_name)

        if remove_extensions:
            dbt_related_changes = self.remove_extensions(dbt_related_changes)

        return dbt_related_changes
    
    def remove_extensions(self, files: dict[GitChangeType, list[str]]) -> dict[GitChangeType, list[str]]:
        """Remove file extensions from a list of file paths."""
        for change_type, file_list in files.items():
            files[change_type] = [os.path.splitext(file_name)[0] for file_name in file_list]

        return files