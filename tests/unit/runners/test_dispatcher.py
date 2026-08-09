"""Unit tests for the runner dispatcher and dbt version/adapter pinning."""
from unittest.mock import MagicMock, patch

import pytest

from dbt_ci.runners import (
    get_dbt_venv_dir,
    parse_adapter,
    resolve_pinned_dbt_binary,
    run_dbt_command,
)


class TestParseAdapter:
    """Test adapter specification parsing."""

    def test_name_only(self):
        """An unpinned adapter installs the latest compatible version."""
        assert parse_adapter("dbt-bigquery") == ("dbt-bigquery", None)

    def test_single_equals(self):
        """The documented 'adapter=version' spelling is supported."""
        assert parse_adapter("dbt-duckdb=1.10.0") == ("dbt-duckdb", "1.10.0")

    def test_double_equals(self):
        """The pip-style 'adapter==version' spelling is supported too."""
        assert parse_adapter("dbt-duckdb==1.10.0") == ("dbt-duckdb", "1.10.0")

    def test_missing_version_after_separator(self):
        """A trailing separator is a user error rather than a bogus requirement."""
        with pytest.raises(ValueError, match="version separator"):
            parse_adapter("dbt-duckdb=")

    def test_missing_name(self):
        """An empty adapter name is rejected."""
        with pytest.raises(ValueError, match="Invalid adapter format"):
            parse_adapter("=1.0.0")


class TestVenvDir:
    """Test the cache location for pinned environments."""

    def test_version_and_adapter_get_distinct_dirs(self):
        """Different version/adapter combinations must not share an environment."""
        first = get_dbt_venv_dir("1.10.13", "dbt-duckdb=1.10.0")
        second = get_dbt_venv_dir("1.10.13", "dbt-bigquery")

        assert first != second
        assert first.name == "dbt-1.10.13+dbt-duckdb-1.10.0"
        assert second.name == "dbt-1.10.13+dbt-bigquery"


class TestResolvePinnedDbtBinary:
    """Test which runners honour --dbt-version/--adapter."""

    def test_returns_none_without_a_pin(self, mock_runner_config):
        """No pin means the runner's own dbt is used."""
        config = mock_runner_config({"runner": "local"})
        assert resolve_pinned_dbt_binary(config) is None

    @pytest.mark.parametrize("runner", ["dbt", "docker", "bash"])
    def test_warns_for_runners_that_cannot_honour_a_pin(self, mock_runner_config, runner):
        """A pin that can't be applied is reported rather than silently ignored."""
        config = mock_runner_config({"runner": runner, "dbt_version": "1.10.13"})

        with patch("dbt_ci.runners.logger") as mock_logger:
            result = resolve_pinned_dbt_binary(config)

        assert result is None
        mock_logger.warning.assert_called_once()

    def test_local_runner_gets_the_venv_binary(self, mock_runner_config, tmp_path):
        """The local runner executes the pinned environment's dbt."""
        config = mock_runner_config({"runner": "local", "dbt_version": "1.10.13"})
        venv_dir = tmp_path / "dbt-1.10.13"

        with patch("dbt_ci.runners.get_dbt_venv_dir", return_value=venv_dir), \
             patch("dbt_ci.runners.dbt_venv_is_ready", return_value=True):
            result = resolve_pinned_dbt_binary(config)

        assert result == str(venv_dir / "bin" / "dbt")

    def test_installs_when_environment_is_not_ready(self, mock_runner_config, tmp_path):
        """A missing or half-installed environment is (re)created before use."""
        config = mock_runner_config({"runner": "local", "adapter": "dbt-duckdb=1.10.0"})
        venv_dir = tmp_path / "env"

        with patch("dbt_ci.runners.get_dbt_venv_dir", return_value=venv_dir), \
             patch("dbt_ci.runners.dbt_venv_is_ready", return_value=False), \
             patch("dbt_ci.runners.create_dbt_venv") as mock_create:
            resolve_pinned_dbt_binary(config)

        mock_create.assert_called_once_with(venv_dir, None, "dbt-duckdb=1.10.0")


class TestRunDbtCommand:
    """Test dispatch to the configured runner."""

    def test_unknown_runner_raises(self, mock_runner_config):
        """An unsupported runner is a configuration error."""
        config = mock_runner_config()
        config["runner"] = "kubernetes"

        with pytest.raises(ValueError, match="Unsupported runner"):
            run_dbt_command(["compile"], config)

    def test_pinned_binary_replaces_the_entrypoint(self, mock_runner_config):
        """The pin only takes effect if the runner actually invokes that binary."""
        config = mock_runner_config({"runner": "local", "dbt_version": "1.10.13"})
        fake_runner = MagicMock(return_value=None)

        with patch("dbt_ci.runners.resolve_pinned_dbt_binary", return_value="/venv/bin/dbt"), \
             patch.dict("dbt_ci.runners.RUNNERS", {"local": fake_runner}):
            run_dbt_command(["compile"], config)

        _, forwarded_config = fake_runner.call_args[0]
        assert forwarded_config["entrypoint"] == "/venv/bin/dbt"

    def test_original_config_is_not_mutated(self, mock_runner_config):
        """Overriding the entrypoint must not leak into the caller's args namespace."""
        config = mock_runner_config({"runner": "local", "dbt_version": "1.10.13"})

        with patch("dbt_ci.runners.resolve_pinned_dbt_binary", return_value="/venv/bin/dbt"), \
             patch.dict("dbt_ci.runners.RUNNERS", {"local": MagicMock(return_value=None)}):
            run_dbt_command(["compile"], config)

        assert config["entrypoint"] == "dbt"
