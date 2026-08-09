"""Unit tests for the report command."""
from argparse import Namespace
from unittest.mock import patch

from dbt_ci.commands.report.index import (
    format_duration,
    render_change_summary,
    render_command_status,
    render_markdown,
    write_report,
)


def _structured(resource_type: str, *names: str) -> dict:
    """Build a structured-nodes mapping as init writes it into the cache."""
    return {
        resource_type: {
            f"{resource_type}.p.{name}": {
                "id": f"{resource_type}.p.{name}",
                "name": name,
                "resource_type": resource_type,
            }
            for name in names
        }
    }


CACHE = {
    "modified_nodes": _structured("model", "customers"),
    "new_nodes": _structured("model", "orders"),
    "deleted_nodes": _structured("model", "legacy"),
}

RUN_REPORT = {
    "init": {
        "status": "completed",
        "started_at": "2026-01-01T00:00:00",
        "completed_at": "2026-01-01T00:00:07.500000",
    },
    "run": {
        "status": "failed",
        "started_at": "2026-01-01T00:01:00",
        "failed_at": "2026-01-01T00:03:30",
    },
}


class TestRenderChangeSummary:
    """Test the change counts and node listings."""

    def test_counts_each_change_type(self):
        """The summary table reports one row per change type."""
        rendered = "\n".join(render_change_summary(CACHE))
        assert "| Modified | 1 |" in rendered
        assert "| New | 1 |" in rendered
        assert "| Deleted | 1 |" in rendered

    def test_lists_node_names(self):
        """Each changed node is named with its resource type."""
        rendered = "\n".join(render_change_summary(CACHE))
        assert "`customers` (model)" in rendered
        assert "`legacy` (model)" in rendered

    def test_reports_no_changes(self):
        """An empty change set says so rather than rendering empty tables."""
        empty = {"modified_nodes": None, "new_nodes": None, "deleted_nodes": None}
        assert "No changes detected" in "\n".join(render_change_summary(empty))

    def test_missing_cache(self):
        """A missing state comparison is reported, not crashed on."""
        assert "No state comparison found." in "\n".join(render_change_summary(None))

    def test_long_lists_are_collapsed(self):
        """Large change sets fold into <details> so the summary stays readable."""
        many = {"modified_nodes": _structured("model", *[f"m{i}" for i in range(25)])}
        rendered = "\n".join(render_change_summary(many))
        assert "<details>" in rendered
        assert "<summary>Modified (25)</summary>" in rendered


class TestRenderCommandStatus:
    """Test the per-command status table."""

    def test_lists_commands_with_icons(self):
        """Each command's terminal status is shown."""
        rendered = "\n".join(render_command_status(RUN_REPORT))
        assert "| `init` | ✅ completed |" in rendered
        assert "| `run` | ❌ failed |" in rendered

    def test_no_report_renders_nothing(self):
        """Without a report there is no command section."""
        assert render_command_status(None) == []


class TestFormatDuration:
    """Test duration formatting from the recorded timestamps."""

    def test_seconds(self):
        """Sub-minute durations render in seconds."""
        assert format_duration(RUN_REPORT["init"]) == "7.5s"

    def test_minutes(self):
        """Longer durations render as minutes and seconds."""
        assert format_duration(RUN_REPORT["run"]) == "2m 30s"

    def test_end_key_follows_the_status(self):
        """The end timestamp key is named after the status, not assumed to be completed_at."""
        entry = {"status": "failed", "started_at": "2026-01-01T00:00:00", "failed_at": "2026-01-01T00:00:05"}
        assert format_duration(entry) == "5.0s"

    def test_missing_timestamps(self):
        """A command still running has no duration to report."""
        assert format_duration({"status": "started", "started_at": "2026-01-01T00:00:00"}) == "-"

    def test_unparseable_timestamps(self):
        """Malformed timestamps degrade rather than raising."""
        assert format_duration({"status": "completed", "started_at": "nope", "completed_at": "nope"}) == "-"


class TestWriteReport:
    """Test where the rendered report is written."""

    def test_writes_to_explicit_output(self, tmp_path):
        """--output takes precedence and truncates the file."""
        target = tmp_path / "report.md"
        write_report("# hello", Namespace(output=str(target)))
        assert target.read_text(encoding="utf-8").strip() == "# hello"

    def test_appends_to_github_step_summary(self, tmp_path, monkeypatch):
        """The job summary accumulates across steps, so it must be appended to."""
        summary = tmp_path / "summary.md"
        summary.write_text("existing\n", encoding="utf-8")
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

        write_report("# added", Namespace(output=None))

        contents = summary.read_text(encoding="utf-8")
        assert "existing" in contents and "# added" in contents

    def test_falls_back_to_stdout(self, capsys, monkeypatch):
        """Outside CI the report goes to stdout."""
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        write_report("# stdout", Namespace(output=None))
        assert "# stdout" in capsys.readouterr().out


class TestRenderMarkdown:
    """Test the assembled document."""

    def test_includes_each_section(self):
        """The report carries a heading, the change summary and the command table."""
        with patch("dbt_ci.commands.report.index.render_exposure_impact", return_value=[]):
            rendered = render_markdown(CACHE, RUN_REPORT, Namespace())

        assert rendered.startswith("## dbt-ci run report")
        assert "| Modified | 1 |" in rendered
        assert "### Commands" in rendered
