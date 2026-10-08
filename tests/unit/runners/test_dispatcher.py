"""Unit tests for the runner dispatcher and dbt version/adapter pinning."""
from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest

from dbt_ci.runners import (
    get_dbt_venv_dir,
    get_dbt_venv_packages,
    parse_adapter,
    resolve_dbt_commands,
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


class TestVenvPackages:
    """Test which distributions a pinned environment installs."""

    def test_v1_installs_dbt_core_and_adapter(self):
        """dbt 1.x comes from dbt-core with the adapter installed alongside."""
        assert get_dbt_venv_packages("1.12.5", "dbt-duckdb=1.12.0") == [
            "dbt-core==1.12.5",
            "dbt-duckdb==1.12.0",
        ]

    def test_v2_installs_the_dbt_distribution(self):
        """dbt v2 is published as `dbt`, not dbt-core."""
        assert get_dbt_venv_packages("2.0.6", None) == ["dbt==2.0.6"]

    def test_v2_skips_the_adapter(self):
        """dbt v2 bundles its adapters, so a separate adapter install is dropped."""
        assert get_dbt_venv_packages("2.0.6", "dbt-bigquery") == ["dbt==2.0.6"]

    def test_adapter_without_version_pin(self):
        """Without a dbt pin the adapter alone decides what gets installed."""
        assert get_dbt_venv_packages(None, "dbt-duckdb") == ["dbt-duckdb"]


class TestResolveDbtCommandsDefer:
    """Test that deferral is explicit so dbt v1 and v2 behave the same."""

    @staticmethod
    def make_args(**overrides) -> Namespace:
        """Build a minimal args namespace for the local runner."""
        values = {
            "runner": "local",
            "dbt_project_dir": "/workspace/dbt",
            "profiles_dir": "/workspace/dbt",
            "reference_state": "/workspace/dbt/.dbtstate",
            "target": None,
            "vars": None,
            "defer": False,
        }
        values.update(overrides)
        return Namespace(**values)

    def test_no_defer_added_when_state_is_passed(self):
        """dbt v2 defers by default once --state is set, so dbt-ci opts out explicitly."""
        commands = resolve_dbt_commands(["run", "--select", "a"], self.make_args())
        assert "--state" in commands
        assert commands[-1] == "--no-defer"

    def test_defer_is_kept_when_requested(self):
        """An explicit --defer must not be contradicted by --no-defer."""
        commands = resolve_dbt_commands(["run"], self.make_args(defer=True))
        assert "--defer" in commands
        assert "--no-defer" not in commands

    def test_clone_is_left_to_defer(self):
        """dbt clone works by deferring to the state manifest."""
        commands = resolve_dbt_commands(["clone", "--select", "a"], self.make_args())
        assert "--no-defer" not in commands

    def test_no_state_means_no_defer_flag(self):
        """Without --state there is nothing to defer to, so no flag is added."""
        commands = resolve_dbt_commands(["run"], self.make_args(reference_state=None))
        assert "--state" not in commands
        assert "--no-defer" not in commands


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


class TestBashRunner:
    """Test that the bash runner gets host paths and can actually start dbt."""

    def test_bash_runner_gets_host_paths(self):
        """--project-dir, --profiles-dir and --state are passed, so --no-defer applies too."""
        args = TestResolveDbtCommandsDefer.make_args(runner="bash")
        commands = resolve_dbt_commands(["ls"], args)
        for flag in ("--project-dir", "--profiles-dir", "--state", "--no-defer"):
            assert flag in commands

    @pytest.mark.parametrize("shell_path, expected", [
        ("/bin/bash", ["/bin/bash", "-c", "dbt ls --select 'tag:a b'"]),
        ("/usr/bin/sh", ["/usr/bin/sh", "-c", "dbt ls --select 'tag:a b'"]),
        ("bin/dbt-wrapper", ["bin/dbt-wrapper", "ls", "--select", "tag:a b"]),
    ])
    def test_shell_runs_the_entrypoint(self, shell_path, expected):
        """A plain shell runs the dbt entrypoint; a wrapper script gets the dbt arguments."""
        from dbt_ci.runners.bash import bash_runner

        with patch("dbt_ci.runners.bash.subprocess.run") as mock_run:
            bash_runner(["ls", "--select", "tag:a b"], {"shell_path": shell_path, "entrypoint": "dbt", "quiet": True})
        assert mock_run.call_args.kwargs["args"] == expected


class TestDryRunSkipsPinnedInstall:
    """Test that a dry run never installs a pinned dbt version."""

    def test_pinned_version_is_not_installed(self):
        """resolve_pinned_dbt_binary (which pip-installs) is skipped on a dry run."""
        from dbt_ci.runners import run_dbt_command

        runner = MagicMock(return_value=None)
        with patch.dict("dbt_ci.runners.RUNNERS", {"local": runner}), \
             patch("dbt_ci.runners.resolve_pinned_dbt_binary") as mock_resolve:
            run_dbt_command(["ls"], {"runner": "local", "dry_run": True, "dbt_version": "1.10.13"})
        mock_resolve.assert_not_called()
        runner.assert_called_once()
