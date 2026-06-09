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
    """Adapter for git operations used during state comparison."""

    provider = os.getenv("GIT_PROVIDER", "github").lower()

    def __init__(self, args: Namespace):
        self.args: Namespace = args
        self.head_branch = self._resolve_head_branch()

        subprocess.run(
            ["git", "fetch", "origin", self.head_branch],
            check=True,
            capture_output=False,
        )

        result = subprocess.run(
            ["git", "diff", "--name-status", f"origin/{self.head_branch}", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )

        self.changes: list[list[str]] = [line.split("\t") for line in result.stdout.splitlines()]

    def _resolve_head_branch(self) -> str:
        """Resolve the base branch to diff against, in priority order:
        1. --base-ref / config file / DBT_CI_BASE_REF (via args)
        2. GITHUB_BASE_REF (set by GitHub Actions on pull_request events)
        3. git symbolic-ref after auto-detecting origin/HEAD
        4. Probe for origin/main or origin/master
        """
        # 1. Explicit value from CLI, config file, or DBT_CI_BASE_REF
        base_ref = getattr(self.args, "base_ref", None)
        if base_ref:
            return base_ref

        # 2. GitHub Actions env var
        github_base_ref = os.environ.get("GITHUB_BASE_REF")
        if github_base_ref:
            return github_base_ref.strip()

        # 3. Try git symbolic-ref; if origin/HEAD isn't set, ask git to auto-detect it first
        result = subprocess.run(
            ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            subprocess.run(
                ["git", "remote", "set-head", "origin", "--auto"],
                capture_output=True,
            )
            result = subprocess.run(
                ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
                capture_output=True,
                text=True,
            )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split("/")[-1]

        # 4. Probe common default branch names
        for branch in ("main", "master"):
            probe = subprocess.run(
                ["git", "rev-parse", "--verify", f"origin/{branch}"],
                capture_output=True,
            )
            if probe.returncode == 0:
                return branch

        raise RuntimeError(
            "Could not determine the base branch for git diff. "
            "Pass --base-ref <branch>, set DBT_CI_BASE_REF, or run "
            "'git remote set-head origin --auto' before invoking dbt-ci."
        )

    def get_changed_files(
        self,
        remove_extensions: bool = False,
        extensions: list[Literal[".sql", ".yml", ".yaml", ".py"]] | None = None
    ) -> dict[GitChangeType, list[str]]:
        """Return a list of changed files with their change types."""
        dbt_project_dir: str | None = getattr(self.args, "dbt_project_dir", None)
        if dbt_project_dir is None:
            raise ValueError("DBT project directory not specified in arguments.")

        dbt_related_changes: dict[GitChangeType, list[str]] = {}
        for change in self.changes:
            change_type = change[0]
            change_type_key: GitChangeType | None = cast(
                GitChangeType | None, GIT_STATUS_MAPPING.get(change_type, None)
            )
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
