"""Unit tests for the git adapter used during state comparison."""
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
