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
