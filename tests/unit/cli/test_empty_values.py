"""Tests for empty CLI and config values counting as not set."""

import os
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner

from dbt_ci.cli.command import drop_empty_option_values
from dbt_ci.main import cli

RUN = "dbt_ci.commands.run.cli.run"
INIT = "dbt_ci.commands.init.cli.init"


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Run inside an empty directory with a clean DBT_* environment and cache."""
    monkeypatch.chdir(tmp_path)
    # The config loader injects values via os.environ.setdefault; keep runs independent.
    for key in list(os.environ):
        if key.startswith("DBT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DBT_CI_CACHE_DIR", str(tmp_path))
    return tmp_path


def resolved(target: str, cli_args=(), env=None):
    """Invoke a command with its implementation stubbed and return its parsed arguments."""
    captured = {}
    command = target.split(".")[2]
    with patch(target, side_effect=lambda args: captured.update(args=args)):
        result = CliRunner().invoke(cli, [command, *cli_args], env=env or {})
    assert result.exit_code in (0, None), result.output
    return captured["args"]


def _params():
    """Options shaped like dbt-ci's: value options, a flag and a repeatable option."""
    return [
        click.Option(["--target", "-t"]),
        click.Option(["--vars"]),
        click.Option(["--defer"], is_flag=True),
        click.Option(["--filters", "-f"], multiple=True),
    ]


class TestDropEmptyOptionValues:
    """Test which arguments are removed before Click parses them."""

    @pytest.mark.parametrize(
        "args",
        [
            ["--target", ""],
            ["--target", "   "],
            ["-t", ""],
            ["--target="],
            ["--filters", ""],
        ],
    )
    def test_empty_values_are_dropped(self, args):
        """Long, short and --opt= forms, whitespace and repeatable options all count."""
        assert drop_empty_option_values(_params(), args) == []

    def test_other_arguments_are_kept(self):
        """Set values, flags and unknown options pass through unchanged."""
        args = ["--target", "ci", "--vars", "", "--defer", "--unknown", "", "--vars={a: 1}"]
        assert drop_empty_option_values(_params(), args) == [
            "--target",
            "ci",
            "--defer",
            "--unknown",
            "",
            "--vars={a: 1}",
        ]

    def test_arguments_after_double_dash_are_untouched(self):
        """Everything after -- belongs to something else."""
        args = ["--", "--target", ""]
        assert drop_empty_option_values(_params(), args) == args


class TestEmptyCliValues:
    """Test that an empty flag falls through to the next source."""

    def test_config_file_applies(self, project):
        """--target '' leaves the config file's target in place."""
        (project / "dbt-ci.config.yaml").write_text("target: ci\n", encoding="utf-8")
        assert resolved(RUN, ["--target", ""]).target == "ci"

    def test_selected_profile_applies(self, project):
        """An empty flag does not wipe a profile's value either."""
        (project / "dbt-ci.config.yaml").write_text(
            "profiles:\n  action:\n    vars: '{a: 1}'\n", encoding="utf-8"
        )
        assert resolved(INIT, ["--profile", "action", "--vars", ""]).vars == "{a: 1}"

    def test_environment_applies(self, project):
        """Without a config value, the environment variable is used."""
        assert resolved(RUN, ["--target="], env={"DBT_TARGET": "prod"}).target == "prod"

    def test_unset_everywhere_is_none(self, project):
        """With nothing else set, the option is simply unset, so init's value is inherited."""
        assert resolved(RUN, ["--target", "", "--vars", ""]).target is None

    def test_empty_profile_flag_uses_environment(self, project):
        """--profile '' falls back to DBT_CI_PROFILE."""
        (project / "dbt-ci.config.yaml").write_text(
            "profiles:\n  action:\n    target: ci\n", encoding="utf-8"
        )
        args = resolved(INIT, ["--profile", ""], env={"DBT_CI_PROFILE": "action"})
        assert args.target == "ci"

    def test_empty_integer_is_not_a_type_error(self, project):
        """--downstream-depth '' used to fail as 'not a valid integer'."""
        assert resolved(RUN, ["--downstream-depth", ""]).downstream_depth is None
        assert resolved(RUN, ["--retries", ""]).retries is None

    def test_subcommand_of_a_group(self, project):
        """Subcommands such as `ephemeral destroy` get the same treatment."""
        (project / "dbt-ci.config.yaml").write_text("target: ci\n", encoding="utf-8")
        captured = {}
        with patch(
            "dbt_ci.commands.ephemeral.cli.destroy",
            side_effect=lambda args: captured.update(args=args),
        ):
            result = CliRunner().invoke(cli, ["ephemeral", "destroy", "--target", ""])
        assert result.exit_code in (0, None), result.output
        assert captured["args"].target == "ci"


class TestEmptyConfigValues:
    """Test that an empty value in the config file counts as not set."""

    def test_empty_string_falls_through_to_environment(self, project):
        """target: "" is the same as leaving target out."""
        (project / "dbt-ci.config.yaml").write_text('target: ""\n', encoding="utf-8")
        assert resolved(RUN, env={"DBT_TARGET": "prod"}).target == "prod"

    def test_empty_env_reference_falls_through(self, project):
        """A ${VAR} that is set but empty counts as not set."""
        (project / "dbt-ci.config.yaml").write_text(
            "init:\n  state-uri: ${STATE_BUCKET_URI}\n", encoding="utf-8"
        )
        args = resolved(INIT, env={"STATE_BUCKET_URI": "", "DBT_STATE_URI": "gs://b/m.json"})
        assert args.state_uri == "gs://b/m.json"
