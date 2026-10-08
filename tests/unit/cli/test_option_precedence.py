"""Tests for how CLI flags, the config file and environment variables are resolved.

The documented order is CLI flag > dbt-ci.config.yaml > shell environment > default.
Options are only wired into the config file if they carry make_config_callback, so a
missing callback silently drops that option's config key — these tests pin the behaviour
per command rather than trusting the option definitions to stay consistent.
"""
import os
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from dbt_ci.main import cli

CONFIG = """
runner: bash
run:
  nodes: models
finalize:
  artifacts-uri: s3://from-config/
  clean-ephemeral: true
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Run inside a directory containing a dbt-ci.config.yaml."""
    (tmp_path / "dbt-ci.config.yaml").write_text(CONFIG, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    # The config loader injects values via os.environ.setdefault; keep runs independent.
    for key in list(os.environ):
        if key.startswith("DBT_"):
            monkeypatch.delenv(key, raising=False)
    return tmp_path


def resolve(command: str, attribute: str, patch_path: str, cli_args=(), env=None):
    """Invoke a command with its implementation stubbed and return one resolved option."""
    captured = {}

    def capture(args):
        captured["value"] = getattr(args, attribute, None)

    with patch(patch_path, side_effect=capture):
        result = CliRunner().invoke(cli, [command, *cli_args], env=env or {}, catch_exceptions=False)

    assert result.exit_code in (0, None), result.output
    return captured.get("value")


class TestCommonOptionPrecedence:
    """Test resolution for an option shared by every command."""

    def test_config_file_is_used(self, project):
        """A value in the config file applies without any flag or variable."""
        assert resolve("run", "runner", "dbt_ci.commands.run.cli.run") == "bash"

    def test_config_file_beats_shell_environment(self, project):
        """A committed config value outranks whatever the runner happens to export."""
        value = resolve(
            "run", "runner", "dbt_ci.commands.run.cli.run", env={"DBT_RUNNER": "local"}
        )
        assert value == "bash"

    def test_cli_flag_wins(self, project):
        """An explicit flag beats both the config file and the environment."""
        value = resolve(
            "run",
            "runner",
            "dbt_ci.commands.run.cli.run",
            cli_args=["--runner", "docker"],
            env={"DBT_RUNNER": "local"},
        )
        assert value == "docker"

    def test_environment_applies_without_a_config_entry(self, tmp_path, monkeypatch):
        """With no config file the environment variable is still honoured."""
        monkeypatch.chdir(tmp_path)
        value = resolve(
            "run", "runner", "dbt_ci.commands.run.cli.run", env={"DBT_RUNNER": "local"}
        )
        assert value == "local"


class TestCommandSectionsReachTheirOptions:
    """Test that per-command config sections are actually consumed.

    Each of these keys is accepted by the config schema and shown in the README, but was
    ignored at runtime because the option had no config callback to read it.
    """

    def test_run_nodes(self, project):
        """run.nodes selects the run mode."""
        assert resolve("run", "nodes", "dbt_ci.commands.run.cli.run") == "models"

    def test_finalize_artifacts_uri(self, project):
        """finalize.artifacts-uri selects the upload destination."""
        value = resolve("finalize", "artifacts_uri", "dbt_ci.commands.finalize.cli.finalize")
        assert value == "s3://from-config/"

    def test_finalize_clean_ephemeral(self, project):
        """Boolean flags are read from the config file too."""
        value = resolve("finalize", "clean_ephemeral", "dbt_ci.commands.finalize.cli.finalize")
        assert value is True

    def test_finalize_artifacts_uri_flag_still_wins(self, project):
        """The flag continues to override the config entry."""
        value = resolve(
            "finalize",
            "artifacts_uri",
            "dbt_ci.commands.finalize.cli.finalize",
            cli_args=["--artifacts-uri", "s3://from-cli/"],
        )
        assert value == "s3://from-cli/"


class TestDeferFlagFallback:
    """Test that DEFER_FLAG enables deferral when nothing more specific sets it."""

    RUN = "dbt_ci.commands.run.cli.run"

    @pytest.fixture(autouse=True)
    def clean_env(self, tmp_path, monkeypatch):
        """Run without a config file and without inherited defer variables."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DBT_DEFER", raising=False)
        monkeypatch.delenv("DEFER_FLAG", raising=False)

    @pytest.mark.parametrize("value", ["--defer", "true", "1", " --defer "])
    def test_enables_defer(self, value):
        """The literal dbt flag and truthy values both turn deferral on."""
        assert resolve("run", "defer", self.RUN, env={"DEFER_FLAG": value}) is True

    @pytest.mark.parametrize("value", ["", "--no-defer", "false", "0"])
    def test_leaves_defer_off(self, value):
        """An empty or falsy DEFER_FLAG keeps deferral off."""
        assert resolve("run", "defer", self.RUN, env={"DEFER_FLAG": value}) is False

    def test_unset_means_no_defer(self):
        """Without DEFER_FLAG the default still applies."""
        assert resolve("run", "defer", self.RUN) is False

    def test_dbt_defer_wins(self):
        """DBT_DEFER is the documented variable, so it outranks DEFER_FLAG."""
        value = resolve("run", "defer", self.RUN, env={"DBT_DEFER": "false", "DEFER_FLAG": "--defer"})
        assert value is False

    def test_config_file_wins(self, tmp_path):
        """A defer entry in the config file outranks DEFER_FLAG."""
        (tmp_path / "dbt-ci.config.yaml").write_text("defer: false\n", encoding="utf-8")
        assert resolve("run", "defer", self.RUN, env={"DEFER_FLAG": "--defer"}) is False

    def test_cli_flag_wins(self):
        """--defer on the command line applies regardless of DEFER_FLAG."""
        value = resolve("run", "defer", self.RUN, cli_args=["--defer"], env={"DEFER_FLAG": ""})
        assert value is True

    def test_invalid_value_is_rejected(self):
        """An unrecognised DEFER_FLAG fails loudly instead of silently not deferring."""
        with patch(self.RUN):
            result = CliRunner().invoke(cli, ["run"], env={"DEFER_FLAG": "--favor-state"})
        assert result.exit_code != 0
        assert "DEFER_FLAG" in result.output
