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

# Commits fetched per step when a shallow clone lacks the merge base: 50, then 200 more,
# then 1000 more, so a recent branch costs one small fetch and an old one still resolves
DEEPEN_STEPS = (50, 200, 1000)


class GitAdapter:
    """Adapter for git operations used during state comparison."""

    def __init__(self, args: Namespace, best_effort: bool = False):
        """
        Fetch the base branch and diff HEAD against it.

        best_effort=True is for callers that can do without git and only trust the diff
        when merge_base_found is True: git never prompts for credentials, its fetch
        output is not printed, and a missing merge base is not warned about.
        """
        self.args: Namespace = args
        self.best_effort = best_effort
        # Whether the diff is against the merge base (True) or the base branch tip
        self.merge_base_found = False
        self.base_branch = self._resolve_base_branch()

        subprocess.run(
            ["git", "fetch", "origin", self.base_branch],
            check=True,
            capture_output=best_effort,
            env=self._fetch_env(),
        )

        self.changes: list[list[str]] = self._diff_against_base()

    def _diff_against_base(self) -> list[list[str]]:
        """
        Diff HEAD against the merge base with the base branch.

        The three-dot form is what CI wants: it reports only what this branch changed,
        whereas a two-dot diff also reports commits landed on the base branch since the
        branch point as (reversed) changes, inflating the change set. Shallow clones
        often lack the merge base, so more history is fetched until it turns up. Only if
        that fails is the two-dot form used, with a warning that the change set may
        include other people's changes.
        """
        base = f"origin/{self.base_branch}"
        three_dot = ["git", "diff", "--name-status", f"{base}...HEAD"]
        result = subprocess.run(three_dot, capture_output=True, text=True)
        if result.returncode != 0 and self._deepen_until_merge_base(base):
            result = subprocess.run(three_dot, capture_output=True, text=True)
        if result.returncode == 0:
            self.merge_base_found = True
            return [line.split("\t") for line in result.stdout.splitlines()]

        logger.debug(f"'{' '.join(three_dot)}' failed: {result.stderr.strip()}")
        if not getattr(self, "best_effort", False):
            logger.warning(self._missing_merge_base_message(base))

        two_dot = ["git", "diff", "--name-status", base, "HEAD"]
        result = subprocess.run(two_dot, capture_output=True, text=True)
        if result.returncode == 0:
            return [line.split("\t") for line in result.stdout.splitlines()]

        logger.debug(f"'{' '.join(two_dot)}' failed: {result.stderr.strip()}")
        raise RuntimeError(
            f"Could not diff against '{base}'. Ensure the base branch has been fetched and "
            "that the repository has enough history (e.g. actions/checkout with "
            "fetch-depth: 0)."
        )

    def _deepen_until_merge_base(self, base: str) -> bool:
        """
        Fetch more history of a shallow clone until HEAD and the base branch meet.

        CI checkouts are often shallow (actions/checkout fetches one commit by default),
        so the commit this branch started from is missing. Deepening in growing steps
        usually finds it within a few fetches without downloading the whole history.
        Returns True once the merge base exists; False if the clone is not shallow or
        the history ran out.
        """
        shallow = subprocess.run(
            ["git", "rev-parse", "--is-shallow-repository"], capture_output=True, text=True
        )
        if shallow.stdout.strip() != "true":
            return False

        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
        head_sha = head.stdout.strip() if head.returncode == 0 else ""

        fetched = 0
        for depth in DEEPEN_STEPS:
            fetched += depth
            logger.info(
                f"Shallow clone: fetching {fetched} more commits of history to find where "
                f"this branch started from '{base}'..."
            )
            if not self._deepen(depth, head_sha):
                return False
            merge_base = subprocess.run(
                ["git", "merge-base", base, "HEAD"], capture_output=True, text=True
            )
            if merge_base.returncode == 0:
                logger.info(f"Found where this branch started from '{base}'.")
                return True
        return False

    def _deepen(self, depth: int, head_sha: str) -> bool:
        """
        Deepen the history of both the base branch and HEAD by `depth` commits.

        Fetching only the base branch deepens its history, but whether HEAD's history
        (e.g. the parents of a PR merge commit) comes along depends on the git version,
        so HEAD's commit is asked for explicitly. A remote that refuses to serve a commit
        by its ID gets a second request for the base branch alone.
        """
        base_only = ["git", "fetch", f"--deepen={depth}", "origin", self.base_branch]
        attempts = [base_only + [head_sha], base_only] if head_sha else [base_only]
        for command in attempts:
            result = subprocess.run(command, capture_output=True, text=True, env=self._fetch_env())
            if result.returncode == 0:
                return True
            logger.debug(f"'{' '.join(command)}' failed: {result.stderr.strip()}")
        return False

    def _fetch_env(self) -> dict[str, str] | None:
        """Return the environment for fetches: no credential prompts in best-effort mode."""
        if not getattr(self, "best_effort", False):
            return None
        return {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    @staticmethod
    def _missing_merge_base_message(base: str) -> str:
        """Explain that the merge base is missing, what that does and how to fix it."""
        shallow = subprocess.run(
            ["git", "rev-parse", "--is-shallow-repository"], capture_output=True, text=True
        )
        if shallow.stdout.strip() == "true":
            cause = (
                "This is a shallow clone without enough history. Fetch the full history, "
                "e.g. actions/checkout with fetch-depth: 0 or GIT_DEPTH: 0 in GitLab CI."
            )
        else:
            cause = (
                f"HEAD and '{base}' share no history. Check that --base-ref names the "
                "branch this one was created from."
            )
        return (
            f"Could not find where this branch started from '{base}', so changes are "
            f"compared with the latest '{base}' instead. Changes merged into it since this "
            f"branch was created may be counted as this branch's own. {cause}"
        )

    def _resolve_base_branch(self) -> str:
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
        extensions: list[Literal[".sql", ".yml", ".yaml", ".py"]] | None = None,
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
                file_name = file_path[len(project_prefix) + 1 :]
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

    def remove_extensions(
        self, files: dict[GitChangeType, list[str]]
    ) -> dict[GitChangeType, list[str]]:
        """Remove file extensions from a list of file paths."""
        for change_type, file_list in files.items():
            files[change_type] = [os.path.splitext(file_name)[0] for file_name in file_list]

        return files
