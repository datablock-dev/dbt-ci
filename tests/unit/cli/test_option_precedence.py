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


class TestNotifications:
    """Test that the notifications section of the config file reaches its options."""

    INIT = "dbt_ci.commands.init.cli.init"

    @pytest.fixture(autouse=True)
    def clean_env(self, tmp_path, monkeypatch):
        """Run without a config file and without inherited notification variables."""
        monkeypatch.chdir(tmp_path)
        for key in ("DBT_NOTIFICATIONS_FORMAT", "DBT_NOTIFICATIONS_PROVIDER", "DBT_NOTIFICATIONS_WEBHOOK",
                    "SLACK_WEBHOOK", "SLACK_WEBHOOK_URL"):
            monkeypatch.delenv(key, raising=False)

    def write_config(self, tmp_path, text):
        """Write a dbt-ci.config.yaml into the working directory."""
        (tmp_path / "dbt-ci.config.yaml").write_text(text, encoding="utf-8")

    def test_defaults(self):
        """Without any setting Slack and the default layout are used."""
        assert resolve("init", "notifications_provider", self.INIT) == "slack"
        assert resolve("init", "notifications_format", self.INIT) == "default"

    def test_config_section_is_used(self, tmp_path):
        """provider, format and webhook are read from the notifications section."""
        self.write_config(tmp_path, "notifications:\n  provider: slack\n  format: json\n  webhook: https://hooks.example/new\n")
        assert resolve("init", "notifications_format", self.INIT) == "json"
        assert resolve("init", "slack_webhook", self.INIT) == "https://hooks.example/new"

    def test_cli_flag_wins(self, tmp_path):
        """--notifications-format overrides the config file."""
        self.write_config(tmp_path, "notifications:\n  format: json\n")
        value = resolve("init", "notifications_format", self.INIT, cli_args=["--notifications-format", "compact"])
        assert value == "compact"

    def test_legacy_top_level_webhook_still_works(self, tmp_path):
        """The released top-level slack-webhook key keeps working."""
        self.write_config(tmp_path, "slack-webhook: https://hooks.example/old\n")
        assert resolve("init", "slack_webhook", self.INIT) == "https://hooks.example/old"

    def test_pr_comment_from_config(self, tmp_path, monkeypatch):
        """notifications.pr-comment turns on report's --pr-comment, and the flag can turn it off."""
        monkeypatch.delenv("DBT_NOTIFICATIONS_PR_COMMENT", raising=False)
        report = "dbt_ci.commands.report.cli.report"
        assert resolve("report", "pr_comment", report) is False
        self.write_config(tmp_path, "notifications:\n  pr-comment: true\n")
        assert resolve("report", "pr_comment", report) is True
        assert resolve("report", "pr_comment", report, cli_args=["--no-pr-comment"]) is False

    def test_section_webhook_wins_over_legacy_key(self, tmp_path):
        """When both spellings are present, notifications.webhook is used."""
        self.write_config(
            tmp_path,
            "slack-webhook: https://hooks.example/old\nnotifications:\n  webhook: https://hooks.example/new\n",
        )
        assert resolve("init", "slack_webhook", self.INIT) == "https://hooks.example/new"


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


class TestDbtLogLevel:
    """Test that dbt-ci's log level never leaves DBT_LOG_LEVEL in a form dbt rejects."""

    @pytest.mark.parametrize("value, expected", [
        ("WARNING", "warn"), ("CRITICAL", "error"), ("INFO", "info"), ("debug", "debug"),
    ])
    def test_environment_is_rewritten_for_dbt(self, value, expected, monkeypatch):
        """dbt only accepts debug/info/warn/error/none in DBT_LOG_LEVEL."""
        from dbt_ci.cli.common_options import normalise_log_level

        monkeypatch.setenv("DBT_LOG_LEVEL", value)
        assert normalise_log_level(value) == value.upper()
        assert os.environ["DBT_LOG_LEVEL"] == expected

    @pytest.mark.parametrize("value, expected", [("warn", "WARNING"), ("none", "CRITICAL")])
    def test_dbt_spellings_are_accepted(self, value, expected, monkeypatch):
        """DBT_LOG_LEVEL=warn (valid for dbt) must not make dbt-ci reject its own option."""
        monkeypatch.chdir(os.path.dirname(__file__))
        monkeypatch.setenv("DBT_LOG_LEVEL", value)
        assert resolve("run", "log_level", "dbt_ci.commands.run.cli.run") == expected

    def test_config_file_value_reaches_dbt_in_its_format(self, tmp_path, monkeypatch):
        """log-level: WARNING in the config is copied into DBT_LOG_LEVEL as 'warn'."""
        monkeypatch.chdir(tmp_path)
        # Set then delete, so the value the config loader injects is removed afterwards
        monkeypatch.setenv("DBT_LOG_LEVEL", "INFO")
        monkeypatch.delenv("DBT_LOG_LEVEL")
        (tmp_path / "dbt-ci.config.yaml").write_text("log-level: WARNING\n", encoding="utf-8")
        assert resolve("run", "log_level", "dbt_ci.commands.run.cli.run") == "WARNING"
        assert os.environ["DBT_LOG_LEVEL"] == "warn"


class TestDockerEnvSplitting:
    """Test that --docker-env values are split into entries without cutting values apart."""

    @pytest.fixture(autouse=True)
    def clean_env(self, tmp_path, monkeypatch):
        """Run without a config file or inherited docker variables."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DBT_DOCKER_ENV", raising=False)

    def test_spaces_in_an_environment_value_are_kept(self):
        """click used to split the variable on whitespace, dropping 'world'."""
        value = resolve("run", "docker_env", "dbt_ci.commands.run.cli.run", env={"DBT_DOCKER_ENV": "A=hello world"})
        assert value == ("A=hello world",)

    def test_commas_and_newlines_still_separate_entries(self):
        """The documented comma and newline separators keep working."""
        value = resolve("run", "docker_env", "dbt_ci.commands.run.cli.run", env={"DBT_DOCKER_ENV": "A=1,B=2\nC=3"})
        assert value == ("A=1", "B=2", "C=3")

    def test_commas_inside_a_value_are_kept(self, tmp_path):
        """A single config entry containing commas is not split."""
        (tmp_path / "dbt-ci.config.yaml").write_text(
            "docker:\n  env:\n    - 'DBT_VARS={\"a\": 1, \"b\": 2}'\n", encoding="utf-8"
        )
        value = resolve("run", "docker_env", "dbt_ci.commands.run.cli.run")
        assert value == ('DBT_VARS={"a": 1, "b": 2}',)
