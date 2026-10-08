"""
Module for Git-related utilities, such as cloning repositories and managing branches.
"""
import logging
import os
import subprocess
from argparse import Namespace
from pathlib import PurePath
from typing import Literal, cast

logger = logging.getLogger(__name__)

# Keyed by the first character of git's status code. Codes carrying a similarity
# score ("R100", "C085") are matched on that first character too.
GIT_STATUS_MAPPING = {
    "M": "modified",
    "A": "added",
    "D": "deleted",
}

type GitChangeType = Literal["modified", "added", "deleted"]


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

        self.changes: list[list[str]] = self._diff_against_base()

    def _diff_against_base(self) -> list[list[str]]:
        """
        Diff HEAD against the merge base with the base branch.

        The three-dot form is what CI wants: it reports only what this branch changed,
        whereas a two-dot diff also reports commits landed on the base branch since the
        branch point as (reversed) changes, inflating the change set. Shallow clones may
        not contain the merge base, so the two-dot form is kept as a fallback.
        """
        base = f"origin/{self.head_branch}"
        attempts = [
            ["git", "diff", "--name-status", f"{base}...HEAD"],
            ["git", "diff", "--name-status", base, "HEAD"],
        ]

        for command in attempts:
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode == 0:
                return [line.split("\t") for line in result.stdout.splitlines()]

            logger.debug(
                f"'{' '.join(command)}' failed ({result.stderr.strip()}). If this repository "
                "was cloned shallowly, fetch more history (e.g. actions/checkout with "
                "fetch-depth: 0) for an accurate change set."
            )

        raise RuntimeError(
            f"Could not diff against 'origin/{self.head_branch}'. Ensure the base branch has "
            "been fetched and that the repository has enough history."
        )

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

        project_prefix = self._project_path_in_repo(dbt_project_dir)

        dbt_related_changes: dict[GitChangeType, list[str]] = {}
        for change_type_key, file_path in self._classify_changes():
            # git reports paths relative to the repository root, while dbt records them
            # relative to the project directory.
            if project_prefix:
                if not file_path.startswith(f"{project_prefix}/"):
                    continue
                file_name = file_path[len(project_prefix) + 1:]
            else:
                file_name = file_path
            if extensions is None or any(file_name.endswith(ext) for ext in extensions):
                dbt_related_changes.setdefault(change_type_key, []).append(file_name)

        if remove_extensions:
            dbt_related_changes = self.remove_extensions(dbt_related_changes)

        return dbt_related_changes

    def _project_path_in_repo(self, dbt_project_dir: str) -> str:
        """
        Return the dbt project directory relative to the repository root, in POSIX form.

        "./dbt", "dbt/" and an absolute path all resolve to "dbt", and a project at the
        repository root resolves to "". Matching on this prefix (rather than a substring)
        keeps "analytics_dbt/models/a.sql" from being read as part of a "dbt" project.
        """
        repo_root = getattr(self, "repo_root", None) or self._resolve_repo_root()
        # git reports the repository root with symlinks resolved, so resolve both sides
        relative = os.path.relpath(os.path.realpath(dbt_project_dir), os.path.realpath(repo_root))
        if relative == ".":
            return ""
        if relative.startswith(".."):
            logger.warning(
                f"dbt project directory '{dbt_project_dir}' is outside the git repository "
                f"'{repo_root}', so no changed files can be matched to it."
            )
        return PurePath(relative).as_posix()

    @staticmethod
    def _resolve_repo_root() -> str:
        """Return the git repository root, or the working directory if it cannot be resolved."""
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return os.getcwd()

    def _classify_changes(self) -> list[tuple[GitChangeType, str]]:
        """
        Turn raw `git diff --name-status` rows into (change type, path) pairs.

        Renames and copies arrive as 'R100\\told\\tnew' / 'C100\\told\\tnew' and carry a
        similarity score, so the status is matched on its first character. A rename is
        expanded into a delete of the old path and an add of the new one. dbt keys nodes
        by unique_id, which a move does not change, so the state comparison reconciles
        such pairs back into a modification of the same node.
        """
        classified: list[tuple[GitChangeType, str]] = []
        for change in self.changes:
            if not change or not change[0]:
                continue

            status = change[0][0]
            if status == "R" and len(change) >= 3:
                classified.append(("deleted", change[1]))
                classified.append(("added", change[-1]))
                continue
            if status == "C" and len(change) >= 3:
                classified.append(("added", change[-1]))
                continue

            change_type_key = cast(GitChangeType | None, GIT_STATUS_MAPPING.get(status, None))
            if change_type_key is None:
                logger.debug(f"Ignoring unsupported git status '{change[0]}' for {change[-1]}")
                continue

            classified.append((change_type_key, change[-1]))

        return classified

    def remove_extensions(self, files: dict[GitChangeType, list[str]]) -> dict[GitChangeType, list[str]]:
        """Remove file extensions from a list of file paths."""
        for change_type, file_list in files.items():
            files[change_type] = [os.path.splitext(file_name)[0] for file_name in file_list]

        return files
