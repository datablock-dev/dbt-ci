"""Unit tests for the report command."""

from argparse import Namespace
from unittest.mock import MagicMock, patch

import json

import pytest

from dbt_ci.commands.report.index import (
    collapsible,
    format_duration,
    load_graph,
    report,
    render_change_summary,
    render_command_status,
    render_exposure_impact,
    render_git_context,
    render_markdown,
    write_report,
)
from dbt_ci.graph.parser import generate_dependency_graph


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

    def test_lists_reasons(self):
        """Each node shows why it is in the change set, as recorded by init."""
        cache = {
            **CACHE,
            "reasons": {
                "model.p.customers": ["`models/customers.sql` changed", "uses changed macro `m`"],
            },
        }
        rendered = "\n".join(render_change_summary(cache))
        assert (
            "- `customers` (model): `models/customers.sql` changed; uses changed macro `m`"
            in rendered
        )
        # Nodes without recorded reasons (e.g. an older cache) are listed as before
        assert "- `orders` (model)\n" in rendered + "\n"

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
        entry = {
            "status": "failed",
            "started_at": "2026-01-01T00:00:00",
            "failed_at": "2026-01-01T00:00:05",
        }
        assert format_duration(entry) == "5.0s"

    def test_missing_timestamps(self):
        """A command still running has no duration to report."""
        assert format_duration({"status": "started", "started_at": "2026-01-01T00:00:00"}) == "-"

    def test_unparseable_timestamps(self):
        """Malformed timestamps degrade rather than raising."""
        assert (
            format_duration({"status": "completed", "started_at": "nope", "completed_at": "nope"})
            == "-"
        )


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


class TestPrComment:
    """Test that report posts the markdown report as a PR comment when asked to."""

    def run_report(self, tmp_path, **args):
        """Run report against a stubbed cache and return the post_pr_comment mock."""
        cache = MagicMock()
        cache.get_cache.side_effect = lambda name=None: (
            RUN_REPORT if name == "report.json" else CACHE
        )
        with (
            patch("dbt_ci.commands.report.index.CacheManager", return_value=cache),
            patch("dbt_ci.commands.report.index.render_exposure_impact", return_value=[]),
            patch("dbt_ci.commands.report.index.post_pr_comment") as post,
        ):
            report(Namespace(output=str(tmp_path / "report.out"), **args))
        return post

    def test_off_by_default(self, tmp_path):
        """Without --pr-comment nothing is posted."""
        assert not self.run_report(tmp_path, format="markdown").called

    def test_posts_the_markdown_report(self, tmp_path):
        """With --pr-comment the same markdown that was written is posted."""
        post = self.run_report(tmp_path, format="markdown", pr_comment=True)
        posted = post.call_args.args[0]
        assert posted.rstrip("\n") == (tmp_path / "report.out").read_text(encoding="utf-8").rstrip(
            "\n"
        )
        assert "customers" in posted

    def test_comment_is_markdown_even_with_json_output(self, tmp_path):
        """--format json changes the written report only; the comment stays readable."""
        post = self.run_report(tmp_path, format="json", pr_comment=True)
        assert post.call_args.args[0].startswith("## dbt-ci run report")
        assert (tmp_path / "report.out").read_text(encoding="utf-8").lstrip().startswith("{")


def _graph_with_exposures(models: list[str]) -> dict:
    """Parse a manifest where each model feeds an exposure named after it."""
    nodes = {
        f"model.p.{name}": {
            "name": name,
            "resource_type": "model",
            "config": {},
            "depends_on": {"nodes": [], "macros": []},
        }
        for name in models
    }
    exposures = {
        f"exposure.p.{name}_dashboard": {
            "name": f"{name}_dashboard",
            "resource_type": "exposure",
            "depends_on": {"nodes": [f"model.p.{name}"], "macros": []},
        }
        for name in models
    }
    child_map = {f"model.p.{name}": [f"exposure.p.{name}_dashboard"] for name in models}
    child_map.update({exposure_id: [] for exposure_id in exposures})
    parent_map = {exposure_id: e["depends_on"]["nodes"] for exposure_id, e in exposures.items()}
    parent_map.update({node_id: [] for node_id in nodes})
    return generate_dependency_graph(
        {
            "metadata": {},
            "nodes": nodes,
            "exposures": exposures,
            "macros": {},
            "sources": {},
            "child_map": child_map,
            "parent_map": parent_map,
        }
    )


class TestExposureImpact:
    """Test the exposures listed as affected by the change set."""

    def test_modified_new_and_deleted_nodes(self):
        """Modified and new nodes are looked up in the target, deleted ones in the reference."""
        graphs = {
            False: _graph_with_exposures(["customers", "orders"]),
            True: _graph_with_exposures(["legacy"]),
        }
        with patch(
            "dbt_ci.commands.report.index.load_graph",
            side_effect=lambda args, is_reference=False: graphs[is_reference],
        ):
            lines = render_exposure_impact(CACHE, Namespace())
        assert lines[0] == "### ⚠️ Affects 3 exposure(s)"
        assert lines[2:5] == [
            "- `customers_dashboard`",
            "- `legacy_dashboard`",
            "- `orders_dashboard`",
        ]

    def test_only_modified_nodes(self):
        """Without deleted nodes the reference graph is never loaded."""
        loaded = []

        def load(args, is_reference=False):
            loaded.append(is_reference)
            return _graph_with_exposures(["customers"])

        cache = {**CACHE, "deleted_nodes": None}
        with patch("dbt_ci.commands.report.index.load_graph", side_effect=load):
            render_exposure_impact(cache, Namespace())
        assert loaded == [False]

    def test_no_exposures_downstream(self):
        """A change set without exposures downstream adds nothing to the report."""
        with patch(
            "dbt_ci.commands.report.index.load_graph", return_value=_graph_with_exposures([])
        ):
            assert render_exposure_impact(CACHE, Namespace()) == []

    def test_graph_unavailable(self):
        """Without a graph the section is left out rather than failing the report."""
        with patch("dbt_ci.commands.report.index.load_graph", return_value=None):
            assert render_exposure_impact(CACHE, Namespace()) == []

    def test_no_cache(self):
        """Without a change set there is nothing to look up."""
        assert render_exposure_impact(None, Namespace()) == []

    def test_load_graph_failure_is_none(self):
        """A graph that can't be loaded (e.g. no cached manifest) is reported as None."""
        with patch("dbt_ci.commands.report.index.DbtGraph", side_effect=RuntimeError("no cache")):
            assert load_graph(Namespace()) is None


class TestReportCommand:
    """Test the report command's outcomes."""

    def test_no_cache_at_all_fails(self):
        """Without init's cache or a run report there is nothing to render."""
        cache = MagicMock()
        cache.get_cache.return_value = None
        with patch("dbt_ci.commands.report.index.CacheManager", return_value=cache):
            with pytest.raises(SystemExit) as exc:
                report(Namespace(format="markdown"))
        assert exc.value.code == 1

    def test_unexpected_error_fails(self):
        """Any error while rendering fails the command instead of passing silently."""
        with (
            patch("dbt_ci.commands.report.index.CacheManager", side_effect=RuntimeError("boom")),
            patch("dbt_ci.commands.report.index.print_exception") as printed,
        ):
            with pytest.raises(SystemExit) as exc:
                report(Namespace(format="markdown"))
        assert exc.value.code == 1
        assert "boom" in str(printed.call_args.args[0])

    def test_json_output(self, tmp_path):
        """--format json writes the run report and the change set as JSON."""
        cache = MagicMock()
        cache.get_cache.side_effect = lambda name=None: (
            RUN_REPORT if name == "report.json" else {**CACHE, "ids": {"model.p.a"}}
        )
        with patch("dbt_ci.commands.report.index.CacheManager", return_value=cache):
            report(Namespace(format="json", output=str(tmp_path / "report.json")))
        written = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
        assert written["report"]["init"]["status"] == "completed"
        # Sets in the cache are written as lists
        assert written["changes"]["ids"] == ["model.p.a"]


class TestSmallHelpers:
    """Test edge cases of the rendering helpers."""

    def test_command_status_skips_malformed_entries(self):
        """An entry that isn't a mapping is skipped rather than breaking the table."""
        lines = render_command_status({**RUN_REPORT, "bogus": "garbage"})
        assert not any("garbage" in line for line in lines)
        assert any("`run`" in line for line in lines)

    def test_duration_with_non_string_timestamps(self):
        """Timestamps of the wrong type give no duration instead of an error."""
        assert format_duration({"status": "completed", "started_at": 1, "completed_at": 2}) == "-"

    def test_duration_while_still_running(self):
        """A command still running has no end yet, so no duration."""
        assert format_duration({"status": "started", "started_at": "2026-01-01T00:00:00"}) == "-"

    def test_duration_without_end_timestamp(self):
        """A finished status without its end timestamp gives no duration."""
        assert format_duration({"status": "completed", "started_at": "2026-01-01T00:00:00"}) == "-"

    def test_collapsible_without_entries(self):
        """An empty list renders nothing, not an empty heading."""
        assert collapsible("Modified (0)", []) == []


class TestRenderGitContext:
    """The line naming the branch, commit, pull request and CI run init recorded."""

    @staticmethod
    def report_with(**git):
        """Return a run report whose init entry recorded the given git context."""
        return {"init": {"status": "completed", "git": git}}

    def test_pull_request(self):
        """A pull request shows its branch into its base, commit, number and run."""
        lines = render_git_context(
            self.report_with(
                provider="GitHub Actions",
                event="pull-request",
                branch="feature/x",
                base_branch="main",
                commit="0123456789abcdef",
                pull_request=42,
                run_url="https://github.com/acme/a/actions/runs/1",
            )
        )
        assert lines[0] == (
            "`feature/x` → `main` · commit `0123456` · PR #42 · GitHub Actions pull-request "
            "([run](https://github.com/acme/a/actions/runs/1))"
        )

    def test_push_to_the_base_branch(self):
        """A branch equal to its base is named once, and unknown values are left out."""
        lines = render_git_context(self.report_with(branch="main", base_branch="main"))
        assert lines[0] == "`main`"

    def test_older_report_has_no_line(self):
        """Reports recorded before init kept the git context render nothing."""
        assert render_git_context({"init": {"status": "completed"}}) == []
        assert render_git_context(None) == []

    def test_markdown_and_json_include_it(self, tmp_path):
        """The markdown report opens with the line, and the JSON report has a git key."""
        run_report = self.report_with(branch="feature/x", commit="abcdef1234")
        assert "`feature/x` · commit `abcdef1`" in render_markdown(None, run_report, Namespace())
        cache = MagicMock()
        cache.get_cache.side_effect = lambda name=None: (
            run_report if name == "report.json" else None
        )
        with patch("dbt_ci.commands.report.index.CacheManager", return_value=cache):
            report(Namespace(format="json", output=str(tmp_path / "r.json")))
        written = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
        assert written["git"] == {"branch": "feature/x", "commit": "abcdef1234"}
