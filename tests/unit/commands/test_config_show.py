"""Tests for `dbt-ci config show`."""

import json
import os

import pytest
from click.testing import CliRunner

from dbt_ci.main import cli

CONFIG = """
runner: bash
init:
  reference-target: production
  state-uri: gs://${STATE_BUCKET}/manifest.json
notifications:
  webhook: https://hooks.slack.com/services/SECRET
profiles:
  action:
    target: ci
    defer: true
    init:
      comparison-strategy: dbt
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Run inside a directory with a profiled config file and an empty cache directory."""
    (tmp_path / "dbt-ci.config.yaml").write_text(CONFIG, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    # The config loader injects values via os.environ.setdefault; keep runs independent.
    for key in list(os.environ):
        if key.startswith(("DBT_", "SLACK_")):
            monkeypatch.delenv(key, raising=False)
    (tmp_path / "cache").mkdir()
    monkeypatch.setenv("DBT_CI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("STATE_BUCKET", "my-bucket")
    return tmp_path


def show(*args, env=None):
    """Run `dbt-ci config show --json ...` and return the parsed result."""
    result = CliRunner().invoke(cli, ["config", "show", "--json", *args], env=env or {})
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def by_option(data):
    """Index the settings of a show result by option name."""
    return {setting["option"]: setting for setting in data["settings"]}


def record_init(project, **config):
    """Write a cache.json as init would, with the given config block."""
    cache = project / "cache" / "cache.json"
    cache.write_text(json.dumps({"config": config}), encoding="utf-8")


class TestSources:
    """Test that each value is attributed to the layer it came from."""

    def test_every_layer(self, project):
        """CLI, profile, top-level config and environment are told apart."""
        data = show(
            "init", "--profile", "action", "--target-compile", env={"DBT_LOG_LEVEL": "DEBUG"}
        )
        settings = by_option(data)
        assert data["command"] == "init"
        assert data["config_file"] == "dbt-ci.config.yaml"
        assert (data["profile"], data["profile_source"]) == ("action", "command line")
        assert settings["--target"] == {
            "option": "--target",
            "value": "ci",
            "source": "profile 'action'",
            "common": True,
        }
        assert settings["--comparison-strategy"]["source"] == "profile 'action'"
        assert settings["--state-uri"]["value"] == "gs://my-bucket/manifest.json"
        assert settings["--state-uri"]["source"] == "config file"
        assert settings["--runner"]["source"] == "config file"
        assert settings["--target-compile"]["source"] == "command line"
        assert settings["--log-level"]["source"] == "environment (DBT_LOG_LEVEL)"

    def test_secrets_are_masked(self, project):
        """The Slack webhook is shown as set, but not printed."""
        assert by_option(show())["--slack-webhook"]["value"] == "***"

    def test_empty_flag_shows_the_layer_that_applies(self, project):
        """--target '' is ignored, so the profile's target and source are reported."""
        settings = by_option(show("init", "--profile", "action", "--target", ""))
        assert settings["--target"]["source"] == "profile 'action'"

    def test_profile_from_environment(self, project):
        """DBT_CI_PROFILE is reported as the profile's source."""
        data = show(env={"DBT_CI_PROFILE": "action"})
        assert data["profile_source"] == "environment (DBT_CI_PROFILE)"


class TestInheritedFromInit:
    """Test the settings later commands take from init's cache."""

    def test_run_shows_inherited_values(self, project):
        """run reports the profile and vars init recorded."""
        record_init(project, profile="action", target={"target": "cached", "vars": "{x: 1}"})
        data = show("run")
        settings = by_option(data)
        assert data["profile_source"] == "inherited from init"
        assert settings["--vars"] == {
            "option": "--vars",
            "value": "{x: 1}",
            "source": "inherited from init",
            "common": True,
        }
        # The profile sets the target, which wins over the cached one
        assert settings["--target"]["value"] == "ci"

    def test_init_does_not_inherit(self, project):
        """init starts a new run and ignores the previous run's cache."""
        record_init(project, profile="action", target={"vars": "{x: 1}"})
        data = show("init")
        assert data["profile"] is None
        assert "--vars" not in by_option(data)


class TestSelection:
    """Test which command is resolved and which options are listed."""

    def test_defaults_are_hidden_unless_all(self, project):
        """Only chosen values are listed by default; --all adds defaults."""
        assert "--entrypoint" not in by_option(show())
        data = CliRunner().invoke(cli, ["config", "show", "--json", "--all"])
        assert by_option(json.loads(data.output))["--entrypoint"]["source"] == "default"

    def test_command_options_come_first(self, project):
        """The command's own options are listed before the common ones."""
        settings = show("init", "--profile", "action")["settings"]
        flags = [setting["common"] for setting in settings]
        assert flags == sorted(flags)

    def test_subcommand(self, project):
        """Nested commands such as `ephemeral destroy` are resolved."""
        assert show("ephemeral", "destroy")["command"] == "ephemeral destroy"

    def test_group_without_subcommand(self, project):
        """`ephemeral` alone shows the options of its default action."""
        assert show("ephemeral")["command"] == "ephemeral"

    def test_unknown_command(self, project):
        """A typo lists the commands that exist."""
        result = CliRunner().invoke(cli, ["config", "show", "rnu"])
        assert result.exit_code == 2
        assert "Unknown command 'rnu'" in result.output

    def test_unknown_profile(self, project):
        """An unknown profile fails as it would in a real run."""
        result = CliRunner().invoke(cli, ["config", "show", "init", "--profile", "acton"])
        assert result.exit_code == 2
        assert "Available profiles: action" in result.output


class TestTable:
    """Test the default text output."""

    def test_sections_and_header(self, project):
        """The table names the command, config file and profile, then two sections."""
        result = CliRunner().invoke(cli, ["config", "show", "init", "--profile", "action"])
        assert result.exit_code == 0, result.output
        assert "Profile:     action (command line)" in result.output
        assert "init options" in result.output
        assert "Common options" in result.output
        assert "--comparison-strategy  dbt" in result.output

    def test_without_config_file(self, tmp_path, monkeypatch):
        """With nothing set, the table says so."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("DBT_CI_CACHE_DIR", str(tmp_path))
        result = CliRunner().invoke(cli, ["config", "show"], env={"DBT_LOG_LEVEL": None})
        assert result.exit_code == 0, result.output
        assert "Config file: none found" in result.output


class TestGenerateStillWorks:
    """Test that `dbt-ci config` without a subcommand still writes the skeleton."""

    def test_config_writes_skeleton(self, tmp_path, monkeypatch):
        """The group keeps its original behaviour and options."""
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(cli, ["config", "--output", "out.yaml"])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "out.yaml").exists()
