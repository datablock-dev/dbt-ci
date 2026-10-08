"""Unit tests for the cache directory manager."""
from argparse import Namespace

import pytest

from dbt_ci.utilities.cache import CacheManager
from dbt_ci.utilities.logging import LOG_FILE_NAME
from dbt_ci.utilities.paths import get_cache_dir


class TestGetCacheDir:
    """Test cache directory resolution."""

    def test_defaults_to_temp_dir(self, monkeypatch):
        """Without an override the cache lives under the system temp directory."""
        monkeypatch.delenv("DBT_CI_CACHE_DIR", raising=False)
        assert get_cache_dir().name == "dbt-ci"

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

    @pytest.mark.parametrize("code, expected", [(0, "completed"), (None, "completed"), (1, "failed"), ("boom", "failed")])
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
