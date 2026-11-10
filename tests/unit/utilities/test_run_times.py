"""Tests for recording node run times and showing them in the report."""

import json
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from dbt_ci.commands.finalize.upload import publish_run_times
from dbt_ci.commands.report.index import render_run_time
from dbt_ci.commands.run.run import record_run_times
from dbt_ci.utilities.cache import CacheManager
from dbt_ci.utilities.run_times import (
    RUN_TIMES_FILE,
    download_run_times,
    format_seconds,
    merge_times,
    node_times,
    read_local_run_times,
    read_node_times,
    sibling_uri,
)

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def write_run_results(project: Path, generated_at: datetime, results: list[dict]) -> None:
    """Write a run_results.json like dbt does."""
    target = project / "target"
    target.mkdir(parents=True, exist_ok=True)
    stamp = generated_at.isoformat().replace("+00:00", "Z")
    (target / "run_results.json").write_text(
        json.dumps({"metadata": {"generated_at": stamp}, "results": results})
    )


def result(node_id: str, seconds, status: str = "success") -> dict:
    """One entry of run_results.json."""
    return {"unique_id": node_id, "execution_time": seconds, "status": status}


class TestReadNodeTimes:
    """Test reading node times from dbt's run_results.json."""

    def test_reads_executed_nodes(self, tmp_path):
        """Executed nodes are kept; skipped, zero-time and malformed entries are not."""
        write_run_results(
            tmp_path,
            NOW + timedelta(seconds=5),
            [
                result("model.p.a", 1.23456),
                result("test.p.t", 0.5, status="fail"),
                result("model.p.skipped", 2.0, status="skipped"),
                result("model.p.zero", 0),
                {"unique_id": "model.p.bad", "execution_time": "fast"},
                {"execution_time": 1.0},
            ],
        )
        assert read_node_times(str(tmp_path), NOW) == {"model.p.a": 1.235, "test.p.t": 0.5}

    def test_stale_file_is_ignored(self, tmp_path):
        """A run_results.json from before the command belongs to an earlier one."""
        write_run_results(tmp_path, NOW - timedelta(minutes=5), [result("model.p.a", 1.0)])
        assert read_node_times(str(tmp_path), NOW) == {}

    def test_small_clock_skew_is_tolerated(self, tmp_path):
        """dbt's timestamp may trail the start time by a moment."""
        write_run_results(tmp_path, NOW - timedelta(seconds=1), [result("model.p.a", 1.0)])
        assert read_node_times(str(tmp_path), NOW) == {"model.p.a": 1.0}

    def test_missing_or_invalid_file(self, tmp_path):
        """No file, invalid JSON or no timestamp record nothing."""
        assert read_node_times(str(tmp_path), NOW) == {}
        (tmp_path / "target").mkdir()
        (tmp_path / "target" / "run_results.json").write_text("{not json")
        assert read_node_times(str(tmp_path), NOW) == {}
        (tmp_path / "target" / "run_results.json").write_text(json.dumps({"results": []}))
        assert read_node_times(str(tmp_path), NOW) == {}

    def test_target_path_from_environment(self, tmp_path, monkeypatch):
        """DBT_TARGET_PATH moves where dbt writes its artifacts."""
        monkeypatch.setenv("DBT_TARGET_PATH", "out")
        (tmp_path / "out").mkdir()
        (tmp_path / "out" / "run_results.json").write_text(
            json.dumps(
                {
                    "metadata": {"generated_at": "2026-11-10T12:00:03"},
                    "results": [result("model.p.a", 2.0)],
                }
            )
        )
        assert read_node_times(str(tmp_path), NOW) == {"model.p.a": 2.0}


class TestStoredTimes:
    """Test the run_times.json document published next to the state."""

    def test_merge_keeps_nodes_not_run(self):
        """This run's times replace the published ones; other nodes keep theirs."""
        merged = merge_times({"nodes": {"a": 1.0, "b": 2.0}}, {"b": 3.0, "c": 4.0})
        assert merged["nodes"] == {"a": 1.0, "b": 3.0, "c": 4.0}
        assert merge_times(None, {"a": 1.0})["nodes"] == {"a": 1.0}

    def test_node_times_validates(self):
        """Only positive numeric times survive."""
        assert node_times({"nodes": {"a": 1, "b": -1, "c": "x", "d": 0.5}}) == {"a": 1.0, "d": 0.5}
        assert node_times(["not", "a", "dict"]) == {}
        assert node_times({"nodes": "x"}) == {}

    def test_sibling_uri(self):
        """The file sits next to the manifest the state URI points at."""
        assert sibling_uri("gs://b/dbt-state/manifest.json", RUN_TIMES_FILE) == (
            "gs://b/dbt-state/run_times.json"
        )
        assert sibling_uri("s3://b/dbt-state/", RUN_TIMES_FILE) == "s3://b/dbt-state/run_times.json"

    def test_download(self):
        """A missing file is no times; an unreadable one warns and is no times."""
        uri = "gs://b/s/run_times.json"
        connector = {"list": MagicMock(return_value=[uri]), "download": MagicMock()}
        connector["download"].return_value = {"nodes": {"a": 1.5}}
        assert download_run_times(uri, connector) == {"a": 1.5}
        connector["list"].return_value = []
        assert download_run_times(uri, connector) == {}
        connector["list"].side_effect = RuntimeError("denied")
        assert download_run_times(uri, connector) == {}

    def test_local_state_dir(self, tmp_path):
        """A local state directory can hold the file too."""
        assert read_local_run_times(str(tmp_path)) == {}
        (tmp_path / RUN_TIMES_FILE).write_text(json.dumps({"nodes": {"a": 2.0}}))
        assert read_local_run_times(str(tmp_path)) == {"a": 2.0}

    def test_format_seconds(self):
        """Durations read naturally at every scale."""
        assert format_seconds(0.42) == "0.4s"
        assert format_seconds(45) == "45s"
        assert format_seconds(185) == "3m 05s"
        assert format_seconds(3720) == "1h 02m"


def _cache(tmp_path: Path) -> CacheManager:
    """A cache in a temporary directory."""
    return CacheManager(Namespace(), cache_dir=tmp_path / "cache")


class TestRecording:
    """Test that run records times in the cache and finalize publishes them."""

    def test_run_records_each_command(self, tmp_path):
        """Times from successive dbt commands accumulate in the cache."""
        cache = _cache(tmp_path)
        args = Namespace(dbt_project_dir=str(tmp_path))
        with patch("dbt_ci.commands.run.run.CacheManager", return_value=cache):
            write_run_results(tmp_path, NOW, [result("seed.p.s", 1.0)])
            record_run_times(args, NOW)
            write_run_results(tmp_path, NOW, [result("model.p.a", 2.0)])
            record_run_times(args, NOW)
        assert cache.get_cache(RUN_TIMES_FILE)["this_run"] == {"seed.p.s": 1.0, "model.p.a": 2.0}

    def test_recording_never_fails_a_run(self, tmp_path):
        """A broken cache is logged, not raised."""
        args = Namespace(dbt_project_dir=str(tmp_path))
        with patch("dbt_ci.commands.run.run.CacheManager", side_effect=OSError("disk")):
            record_run_times(args, NOW)
        record_run_times(Namespace(), NOW)

    def test_finalize_merges_into_published_times(self, tmp_path):
        """finalize adds this run's times to the published ones."""
        cache = _cache(tmp_path)
        cache.add_run_times({"model.p.a": 2.0})
        uri = "gs://b/s/run_times.json"
        connector = {
            "list": MagicMock(return_value=[uri]),
            "download": MagicMock(return_value={"nodes": {"model.p.b": 5.0, "model.p.a": 9.0}}),
        }
        upload = MagicMock()
        publish_run_times("gs://b/s", cache, upload, connector)
        uploaded_uri, document, _ = upload.call_args.args
        assert uploaded_uri == uri
        assert document["nodes"] == {"model.p.b": 5.0, "model.p.a": 2.0}

    def test_finalize_without_times_uploads_nothing(self, tmp_path):
        """A run that built nothing has nothing to publish."""
        upload = MagicMock()
        publish_run_times("gs://b/s", _cache(tmp_path), upload, {})
        upload.assert_not_called()


class TestRenderRunTime:
    """Test the report's run time section."""

    def render(self, tmp_path, run_times: dict | None, graph: dict | None = None) -> str:
        """Render the section from the given cached run times and project graph."""
        cache = _cache(tmp_path)
        if run_times is not None:
            cache._write(run_times, RUN_TIMES_FILE)
        with (
            patch("dbt_ci.commands.report.index.CacheManager", return_value=cache),
            patch("dbt_ci.commands.report.index.load_graph", return_value=graph),
        ):
            return "\n".join(render_run_time(Namespace()))

    def test_nothing_built(self, tmp_path):
        """Without times for this run (e.g. a dry run) there is no section."""
        assert self.render(tmp_path, None) == ""
        assert self.render(tmp_path, {"recorded": {"a": 1.0}}) == ""

    def test_built_and_skipped(self, tmp_path):
        """What was built is compared with the recorded time of the rest of the project."""
        graph = {"model": {"a": {}, "b": {}, "c": {}}, "test": {"t": {}}}
        text = self.render(
            tmp_path,
            {
                "this_run": {"a": 30.0},
                # b and t were left out; gone is no longer in the project
                "recorded": {"a": 25.0, "b": 600.0, "t": 270.0, "gone": 999.0},
            },
            graph,
        )
        assert "Built **1** node(s) in **30s** of dbt run time." in text
        assert "The **2** other node(s) with a recorded run time took about **14m 30s**" in text
        assert "skipped about **97%**" in text
        assert "not wall-clock time" in text

    def test_without_project_graph_all_recorded_nodes_count(self, tmp_path):
        """If the graph can't be loaded, every recorded node not built counts."""
        text = self.render(tmp_path, {"this_run": {"a": 1.0}, "recorded": {"gone": 3.0}})
        assert "The **1** other node(s)" in text

    def test_no_recorded_times(self, tmp_path):
        """Without published times the section says how to get them."""
        text = self.render(tmp_path, {"this_run": {"a": 1.0}})
        assert "Built **1** node(s) in **1.0s**" in text
        assert "dbt-ci finalize" in text
