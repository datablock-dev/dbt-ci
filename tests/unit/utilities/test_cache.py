"""Unit tests for the cache directory manager."""

import json
import tempfile
from pathlib import Path
from argparse import Namespace
from unittest.mock import patch

import pytest

from dbt_ci.utilities.cache import CacheManager
from dbt_ci.utilities.logging import LOG_FILE_NAME
from dbt_ci.utilities.paths import CI_JOB_IDS, CI_JOB_TEMP_DIRS, get_cache_dir


class TestGetCacheDir:
    """Test cache directory resolution."""

    @pytest.fixture
    def outside_ci(self, monkeypatch):
        """Clear the override and every CI variable the cache location looks at."""
        for name in ("DBT_CI_CACHE_DIR", *CI_JOB_TEMP_DIRS, *CI_JOB_IDS):
            monkeypatch.delenv(name, raising=False)

    def test_defaults_to_temp_dir(self, outside_ci):
        """Outside CI and without an override the cache lives under the system temp dir."""
        assert get_cache_dir() == Path(tempfile.gettempdir()) / "dbt-ci"

    @pytest.mark.parametrize("name", CI_JOB_TEMP_DIRS)
    def test_ci_job_temp_dir(self, outside_ci, monkeypatch, tmp_path, name):
        """GitHub Actions and Azure Pipelines jobs use the temp dir the runner gives them."""
        monkeypatch.setenv(name, str(tmp_path))
        assert get_cache_dir() == tmp_path / "dbt-ci"

    @pytest.mark.parametrize("name", CI_JOB_IDS)
    def test_ci_job_id(self, outside_ci, monkeypatch, name):
        """Other CI systems get a directory per job inside the shared dbt-ci directory."""
        monkeypatch.setenv(name, "1234")
        assert get_cache_dir() == Path(tempfile.gettempdir()) / "dbt-ci" / "1234"

    def test_job_id_is_made_safe_for_a_path(self, outside_ci, monkeypatch):
        """Braces and slashes in an ID (Bitbucket's {uuid}) cannot escape the temp dir."""
        monkeypatch.setenv("BITBUCKET_STEP_UUID", "{ab/../cd}")
        assert get_cache_dir() == Path(tempfile.gettempdir()) / "dbt-ci" / "abcd"

    def test_concurrent_jobs_get_different_directories(self, outside_ci, monkeypatch):
        """Two GitLab jobs on one shared runner no longer share a cache."""
        monkeypatch.setenv("CI_JOB_ID", "1")
        first = get_cache_dir()
        monkeypatch.setenv("CI_JOB_ID", "2")
        assert get_cache_dir() != first

    def test_clearing_the_local_cache_keeps_job_caches(self, outside_ci, monkeypatch, tmp_path):
        """A job's cache inside <temp dir>/dbt-ci survives the local cache being cleared."""
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setenv("CI_JOB_ID", "7")
        job_cache = CacheManager(Namespace())
        (job_cache.dir_path / "cache.json").write_text("{}", encoding="utf-8")

        monkeypatch.delenv("CI_JOB_ID")
        local_cache = CacheManager(Namespace())
        (local_cache.dir_path / "cache.json").write_text("{}", encoding="utf-8")
        local_cache.clear_cache()

        assert local_cache.dir_path == tmp_path / "dbt-ci"
        assert not (local_cache.dir_path / "cache.json").exists()
        assert (tmp_path / "dbt-ci" / "7" / "cache.json").exists()

    def test_override_beats_ci_detection(self, outside_ci, monkeypatch, tmp_path):
        """An explicit DBT_CI_CACHE_DIR still wins inside CI."""
        monkeypatch.setenv("RUNNER_TEMP", str(tmp_path / "runner"))
        monkeypatch.setenv("DBT_CI_CACHE_DIR", str(tmp_path / "mine"))
        assert get_cache_dir() == tmp_path / "mine"

    def test_env_var_overrides_location(self, monkeypatch, tmp_path):
        """DBT_CI_CACHE_DIR relocates the cache so concurrent runs can be isolated."""
        monkeypatch.setenv("DBT_CI_CACHE_DIR", str(tmp_path / "run-123"))
        assert get_cache_dir() == tmp_path / "run-123"

    def test_cache_manager_uses_override(self, monkeypatch, tmp_path):
        """CacheManager writes into the overridden directory."""
        monkeypatch.setenv("DBT_CI_CACHE_DIR", str(tmp_path / "run-456"))
        cache = CacheManager(Namespace())
        assert cache.dir_path == (tmp_path / "run-456").resolve()


class TestClearCache:
    """Test that clearing the cache doesn't destroy the active log or crash on directories."""

    def test_removes_cache_files(self, tmp_path):
        """Ordinary cache files are deleted."""
        cache = CacheManager(Namespace(), cache_dir=tmp_path)
        (tmp_path / "cache.json").write_text("{}", encoding="utf-8")

        cache.clear_cache()

        assert not (tmp_path / "cache.json").exists()

    def test_truncates_rather_than_unlinks_the_log(self, tmp_path):
        """The log file stays in place because a FileHandler holds it open for the run."""
        cache = CacheManager(Namespace(), cache_dir=tmp_path)
        log_file = tmp_path / LOG_FILE_NAME
        log_file.write_text("previous run output", encoding="utf-8")

        cache.clear_cache()

        assert log_file.exists()
        assert log_file.read_text(encoding="utf-8") == ""

    def test_skips_subdirectories(self, tmp_path):
        """A directory in the cache folder must not abort the command."""
        cache = CacheManager(Namespace(), cache_dir=tmp_path)
        (tmp_path / "nested").mkdir()
        (tmp_path / "cache.json").write_text("{}", encoding="utf-8")

        cache.clear_cache()

        assert (tmp_path / "nested").is_dir()
        assert not (tmp_path / "cache.json").exists()

    def test_missing_directory_is_a_noop(self, tmp_path):
        """Clearing a cache directory that was already removed does nothing."""
        target = tmp_path / "gone"
        cache = CacheManager(Namespace(), cache_dir=target)
        target.rmdir()

        cache.clear_cache()


class TestTrackReport:
    """Test that a command's report entry is always closed, however the command exits."""

    @staticmethod
    def make_cache(tmp_path):
        """Build a cache with a started 'run' entry."""
        from argparse import Namespace
        from dbt_ci.utilities.cache import CacheManager

        cache = CacheManager(Namespace(), cache_dir=tmp_path)
        cache.start_report("init", Namespace())
        cache.start_report("run", Namespace())
        return cache

    @staticmethod
    def status(cache, command="run"):
        """Read the status of a report entry."""
        return cache.get_cache("report.json")[command]["status"]

    @pytest.mark.parametrize(
        "code, expected", [(0, "completed"), (None, "completed"), (1, "failed"), ("boom", "failed")]
    )
    def test_sys_exit_closes_the_entry(self, tmp_path, code, expected):
        """Dry runs and "nothing to do" paths exit with 0; failures exit non-zero."""
        cache = self.make_cache(tmp_path)
        with pytest.raises(SystemExit):
            with cache.track_report("run"):
                raise SystemExit(code)
        assert self.status(cache) == expected

    def test_exception_marks_failed(self, tmp_path):
        """An unhandled error marks the entry failed and still propagates."""
        cache = self.make_cache(tmp_path)
        with pytest.raises(ValueError):
            with cache.track_report("run"):
                raise ValueError("boom")
        assert self.status(cache) == "failed"

    def test_normal_return_marks_completed(self, tmp_path):
        """A command that returns normally is completed."""
        cache = self.make_cache(tmp_path)
        with cache.track_report("run"):
            pass
        assert self.status(cache) == "completed"

    def test_entry_closed_by_the_command_is_kept(self, tmp_path):
        """A status the command set itself (with its comment) is not overwritten."""
        cache = self.make_cache(tmp_path)
        with pytest.raises(SystemExit):
            with cache.track_report("run"):
                cache.update_report("run", "failed", comment="dbt failed")
                raise SystemExit(0)
        assert self.status(cache) == "failed"
        assert cache.get_cache("report.json")["run"]["comment"] == "dbt failed"

    def test_missing_report_is_ignored(self, tmp_path):
        """A command that cleared the cache (finalize) does not trigger a warning or error."""
        from argparse import Namespace
        from dbt_ci.utilities.cache import CacheManager

        cache = CacheManager(Namespace(), cache_dir=tmp_path)
        with cache.track_report("finalize"):
            pass
        assert cache.get_cache("report.json") is None


class TestWriteCacheConfig:
    """Test the run configuration init records for later commands."""

    def _write(self, tmp_path, **args):
        """Write the cache with the given args and return the recorded config block."""
        defaults = {"comparison_strategy": "hybrid", "runner": "local"}
        cache = CacheManager(Namespace(**{**defaults, **args}), cache_dir=tmp_path / "cache")
        with patch("dbt_ci.utilities.cache.get_profile", return_value={"type": "bigquery"}):
            cache.write_cache()
        return json.loads((tmp_path / "cache" / "cache.json").read_text(encoding="utf-8"))["config"]

    def test_records_reasons(self, tmp_path):
        """init's reasons for each changed node are written next to the change set."""
        cache = CacheManager(
            Namespace(comparison_strategy="dbt", runner="local"), cache_dir=tmp_path / "cache"
        )
        reasons = {"model.p.a": ["code differs from the reference manifest"]}
        with patch("dbt_ci.utilities.cache.get_profile", return_value={"type": "bigquery"}):
            cache.write_cache(reasons=reasons)
        written = json.loads((tmp_path / "cache" / "cache.json").read_text(encoding="utf-8"))
        assert written["reasons"] == reasons

    def test_records_state_as_absolute_path(self, tmp_path, monkeypatch):
        """init records its state directory as absolute, so later commands can pass it on."""
        monkeypatch.chdir(tmp_path)
        config = self._write(tmp_path, reference_state="dbt/.dbtstate")

        assert config["reference"]["state"] == str((tmp_path / "dbt" / ".dbtstate").resolve())

    def test_records_no_state_when_unset(self, tmp_path):
        """Without a state path nothing is recorded, rather than a made-up one."""
        config = self._write(tmp_path)

        assert config["reference"]["state"] is None
