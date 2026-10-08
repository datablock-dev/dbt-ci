"""Unit tests for the git adapter used during state comparison."""
import os
import subprocess
from argparse import Namespace
from unittest.mock import patch

import pytest

from dbt_ci.utilities.git import GitAdapter


def _make_adapter(changes: list[list[str]], dbt_project_dir: str = "dbt") -> GitAdapter:
    """Build a GitAdapter with its git calls bypassed and a fixed set of diff rows."""
    adapter = GitAdapter.__new__(GitAdapter)
    adapter.args = Namespace(dbt_project_dir=dbt_project_dir)
    adapter.head_branch = "main"
    adapter.changes = changes
    # Resolve the project directory against the working directory without calling git
    adapter.repo_root = os.getcwd()
    return adapter


class TestClassifyChanges:
    """Test that raw `git diff --name-status` rows map to change types."""

    def test_plain_statuses(self):
        """M/A/D map to modified/added/deleted."""
        adapter = _make_adapter([
            ["M", "dbt/models/a.sql"],
            ["A", "dbt/models/b.sql"],
            ["D", "dbt/models/c.sql"],
        ])
        assert adapter.get_changed_files() == {
            "modified": ["models/a.sql"],
            "added": ["models/b.sql"],
            "deleted": ["models/c.sql"],
        }

    def test_rename_becomes_delete_plus_add(self):
        """R100 carries a similarity score and must expand into a delete and an add."""
        adapter = _make_adapter([["R100", "dbt/models/old.sql", "dbt/models/new.sql"]])

        result = adapter.get_changed_files()

        assert result["deleted"] == ["models/old.sql"]
        assert result["added"] == ["models/new.sql"]

    def test_copy_becomes_add(self):
        """C085 records a new file at the destination path only."""
        adapter = _make_adapter([["C085", "dbt/models/src.sql", "dbt/models/copy.sql"]])

        result = adapter.get_changed_files()

        assert result["added"] == ["models/copy.sql"]
        assert "deleted" not in result

    def test_modified_status_with_score_is_still_modified(self):
        """A status code carrying a score is matched on its first character."""
        adapter = _make_adapter([["M100", "dbt/models/a.sql"]])
        assert adapter.get_changed_files() == {"modified": ["models/a.sql"]}

    def test_unknown_status_is_skipped(self):
        """Statuses dbt-ci doesn't model (e.g. unmerged) are ignored, not crashed on."""
        adapter = _make_adapter([
            ["U", "dbt/models/conflict.sql"],
            ["M", "dbt/models/a.sql"],
        ])
        assert adapter.get_changed_files() == {"modified": ["models/a.sql"]}

    def test_files_outside_project_dir_are_ignored(self):
        """Changes outside the dbt project directory are not dbt changes."""
        adapter = _make_adapter([
            ["M", "README.md"],
            ["M", "dbt/models/a.sql"],
        ])
        assert adapter.get_changed_files() == {"modified": ["models/a.sql"]}

    def test_extension_filter(self):
        """Only files matching the requested extensions are returned."""
        adapter = _make_adapter([
            ["M", "dbt/models/a.sql"],
            ["M", "dbt/models/schema.yml"],
        ])
        assert adapter.get_changed_files(extensions=[".sql"]) == {"modified": ["models/a.sql"]}


class TestDiffAgainstBase:
    """Test the diff range used to compute the change set."""

    def test_prefers_three_dot_diff(self):
        """The merge-base (three-dot) diff is what isolates this branch's own changes."""
        adapter = GitAdapter.__new__(GitAdapter)
        adapter.head_branch = "main"

        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="M\tdbt/models/a.sql\n", stderr=""
        )
        with patch("dbt_ci.utilities.git.subprocess.run", return_value=completed) as mock_run:
            changes = adapter._diff_against_base()

        assert changes == [["M", "dbt/models/a.sql"]]
        assert mock_run.call_args_list[0][0][0] == [
            "git", "diff", "--name-status", "origin/main...HEAD",
        ]

    def test_falls_back_to_two_dot_when_merge_base_missing(self):
        """Shallow clones may lack the merge base, so a direct diff is attempted next."""
        adapter = GitAdapter.__new__(GitAdapter)
        adapter.head_branch = "main"

        failure = subprocess.CompletedProcess(
            args=[], returncode=128, stdout="", stderr="no merge base"
        )
        success = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="A\tdbt/models/b.sql\n", stderr=""
        )
        with patch("dbt_ci.utilities.git.subprocess.run", side_effect=[failure, success]) as mock_run:
            changes = adapter._diff_against_base()

        assert changes == [["A", "dbt/models/b.sql"]]
        assert mock_run.call_args_list[1][0][0] == [
            "git", "diff", "--name-status", "origin/main", "HEAD",
        ]

    def test_raises_when_both_diffs_fail(self):
        """A completely unusable base ref is an error rather than an empty change set."""
        adapter = GitAdapter.__new__(GitAdapter)
        adapter.head_branch = "main"

        failure = subprocess.CompletedProcess(
            args=[], returncode=128, stdout="", stderr="bad revision"
        )
        with patch("dbt_ci.utilities.git.subprocess.run", return_value=failure):
            with pytest.raises(RuntimeError, match="Could not diff against 'origin/main'"):
                adapter._diff_against_base()


class TestProjectDirMatching:
    """Test that changed paths are matched to the dbt project directory by path, not substring."""

    CHANGES = [
        ["M", "dbt/models/a.sql"],
        ["M", "analytics_dbt/models/b.sql"],
        ["M", "docs/dbt/c.sql"],
        ["M", "README.md"],
    ]

    @pytest.mark.parametrize("project_dir", ["dbt", "./dbt", "dbt/", "dbt/./"])
    def test_spellings_of_the_same_directory(self, project_dir, tmp_path, monkeypatch):
        """Relative spellings of the project directory all match the same files."""
        monkeypatch.chdir(tmp_path)
        adapter = _make_adapter(self.CHANGES, dbt_project_dir=project_dir)
        adapter.repo_root = str(tmp_path)
        assert adapter.get_changed_files() == {"modified": ["models/a.sql"]}

    def test_absolute_project_dir(self, tmp_path, monkeypatch):
        """An absolute project directory inside the repository is matched too."""
        monkeypatch.chdir(tmp_path)
        adapter = _make_adapter(self.CHANGES, dbt_project_dir=str(tmp_path / "dbt"))
        adapter.repo_root = str(tmp_path)
        assert adapter.get_changed_files() == {"modified": ["models/a.sql"]}

    def test_project_at_repository_root(self, tmp_path, monkeypatch):
        """A project at the repository root keeps every path unchanged."""
        monkeypatch.chdir(tmp_path)
        adapter = _make_adapter([["M", "models/a.sql"]], dbt_project_dir=".")
        adapter.repo_root = str(tmp_path)
        assert adapter.get_changed_files() == {"modified": ["models/a.sql"]}

    def test_run_from_a_subdirectory(self, tmp_path, monkeypatch):
        """The project directory is resolved from the working directory, not the repository root."""
        (tmp_path / "ci").mkdir()
        monkeypatch.chdir(tmp_path / "ci")
        adapter = _make_adapter(self.CHANGES, dbt_project_dir="../dbt")
        adapter.repo_root = str(tmp_path)
        assert adapter.get_changed_files() == {"modified": ["models/a.sql"]}

    def test_symlinked_working_directory(self, tmp_path, monkeypatch):
        """A working directory reached through a symlink still matches git's resolved root."""
        real = tmp_path / "real"
        (real / "dbt").mkdir(parents=True)
        link = tmp_path / "link"
        link.symlink_to(real)
        monkeypatch.chdir(link)
        adapter = _make_adapter(self.CHANGES, dbt_project_dir="dbt")
        adapter.repo_root = str(real)
        assert adapter.get_changed_files() == {"modified": ["models/a.sql"]}
