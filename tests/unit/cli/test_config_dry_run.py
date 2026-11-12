"""Tests for dry-run set per command in the config file (`delete: {dry-run: true}`)."""

import os
from contextlib import ExitStack
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from dbt_ci.cli.config.schema import validate_config
from dbt_ci.commands.config.show import resolve_settings
from dbt_ci.main import cli

# The implementation each command line reaches, stubbed so nothing runs
TARGETS = {
    ("delete",): "dbt_ci.commands.delete.cli.delete",
    ("migration",): "dbt_ci.commands.migration.cli.migration",
    ("ephemeral",): "dbt_ci.commands.ephemeral.cli.ephemeral",
    ("ephemeral", "create"): "dbt_ci.commands.ephemeral.cli.ephemeral",
    ("ephemeral", "destroy"): "dbt_ci.commands.ephemeral.cli.destroy",
    ("run",): "dbt_ci.commands.run.cli.run",
}
CACHE_MANAGERS = [
    "dbt_ci.commands.delete.cli.CacheManager",
    "dbt_ci.commands.migration.cli.CacheManager",
    "dbt_ci.commands.ephemeral.cli.CacheManager",
    "dbt_ci.commands.run.cli.CacheManager",
]
PR_ENV = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "pull_request"}


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Run in an empty directory with no DBT_ or CI variables set, returning a config writer."""
    monkeypatch.chdir(tmp_path)
    # The config loader injects values via os.environ.setdefault; keep runs independent.
    for key in list(os.environ):
        if key.startswith(("DBT_", "GITHUB_", "GITLAB_", "CI_", "BUILDKITE")):
            monkeypatch.delenv(key, raising=False)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setenv("DBT_CI_CACHE_DIR", str(cache_dir))

    def write(config: str) -> None:
        """Write dbt-ci.config.yaml with the given contents."""
        (tmp_path / "dbt-ci.config.yaml").write_text(config, encoding="utf-8")

    return write


def invoke(command, cli_args=(), env=None):
    """Invoke a command with its implementation stubbed, returning (result, parsed args)."""
    captured = {}
    with ExitStack() as stack:
        stack.enter_context(patch(TARGETS[command], side_effect=lambda a: captured.update(a=a)))
        for target in CACHE_MANAGERS:
            stack.enter_context(patch(target))
        result = CliRunner().invoke(cli, [*command, *cli_args], env=env or {})
    return result, captured.get("a")


def dry_run(command, cli_args=(), env=None) -> bool:
    """Return the dry_run a command would run with, failing on an error exit."""
    result, args = invoke(command, cli_args, env)
    assert result.exit_code in (0, None), result.output
    return args.dry_run


def show(tokens, env=None):
    """Return (value, source) of --dry-run as `dbt-ci config show` resolves it."""
    with patch.dict(os.environ, env or {}):
        resolved = resolve_settings(cli, tokens)
    return {s.option: (s.value, s.source) for s in resolved.settings}["--dry-run"]


class TestCommandKey:
    """Each command reads its own dry-run key, and only its own."""

    @pytest.mark.parametrize(
        "section, command",
        [
            ("delete", ("delete",)),
            ("migration", ("migration",)),
            ("ephemeral", ("ephemeral", "create")),
            ("ephemeral", ("ephemeral", "destroy")),
            ("ephemeral", ("ephemeral",)),
        ],
    )
    def test_command_key(self, project, section, command):
        """`<section>.dry-run: true` makes the command a dry run."""
        project(f"{section}:\n  dry-run: true\n")
        assert dry_run(command) is True

    def test_underscore_alias(self, project):
        """dry_run is accepted as well as dry-run."""
        project("delete:\n  dry_run: true\n")
        assert dry_run(("delete",)) is True

    def test_other_commands_key_is_ignored(self, project):
        """migration.dry-run does not make delete a dry run, and the other way round."""
        project("migration:\n  dry-run: true\n")
        assert dry_run(("delete",)) is False
        assert dry_run(("migration",)) is True

    def test_run_is_unaffected(self, project):
        """run only reads the top-level key."""
        project(
            "delete:\n  dry-run: true\nmigration:\n  dry-run: true\nephemeral:\n  dry-run: true\n"
        )
        assert dry_run(("run",)) is False


class TestPrecedence:
    """CLI flag > command key > top-level dry-run > DBT_DRY_RUN > false."""

    def test_command_line_wins(self, project):
        """--dry-run beats a command key set to false."""
        project("dry-run: false\ndelete:\n  dry-run: false\n")
        assert dry_run(("delete",), ["--dry-run"]) is True

    def test_top_level_fallback(self, project):
        """Without a command key the top-level dry-run applies, to run as well."""
        project("dry-run: true\n")
        assert dry_run(("delete",)) is True
        assert dry_run(("ephemeral", "destroy")) is True
        assert dry_run(("run",)) is True

    def test_command_key_beats_top_level(self, project):
        """delete.dry-run: false runs delete for real while everything else stays a dry run."""
        project("dry-run: true\ndelete:\n  dry-run: false\n")
        assert dry_run(("delete",)) is False
        assert dry_run(("migration",)) is True

    def test_command_key_beats_the_environment(self, project):
        """The config file sits above DBT_DRY_RUN."""
        project("delete:\n  dry-run: false\n")
        assert dry_run(("delete",), env={"DBT_DRY_RUN": "true"}) is False

    def test_environment_and_default(self, project):
        """DBT_DRY_RUN applies when the config file says nothing, else false."""
        project("target: dev\n")
        assert dry_run(("delete",), env={"DBT_DRY_RUN": "true"}) is True
        assert dry_run(("delete",)) is False


class TestLayers:
    """The command key follows the usual profile and event layering."""

    CONFIG = """
on:
  pull-request:
    delete:
      dry-run: true
    migration:
      dry-run: true
profiles:
  sandbox:
    delete:
      dry-run: true
  prod:
    on:
      pull-request:
        ephemeral:
          dry-run: true
"""

    def test_event_block(self, project):
        """The pull-request block makes delete and migration dry runs on pull requests only."""
        project(self.CONFIG)
        assert dry_run(("delete",), env=PR_ENV) is True
        assert dry_run(("migration",), env=PR_ENV) is True
        assert dry_run(("run",), env=PR_ENV) is False
        assert dry_run(("delete",)) is False

    def test_profile(self, project):
        """A profile's command key applies when the profile is selected."""
        project(self.CONFIG)
        assert dry_run(("delete",), ["--profile", "sandbox"]) is True
        assert dry_run(("migration",), ["--profile", "sandbox"]) is False

    def test_profile_event_block(self, project):
        """A profile's own event block applies too."""
        project(self.CONFIG)
        assert dry_run(("ephemeral", "destroy"), ["--profile", "prod"], env=PR_ENV) is True
        assert dry_run(("ephemeral", "destroy"), ["--profile", "prod"]) is False

    def test_event_command_key_beats_top_level_false(self, project):
        """A command key from an event block beats a top-level dry-run set anywhere."""
        project("dry-run: false\n" + self.CONFIG)
        assert dry_run(("delete",), env=PR_ENV) is True


class TestConfigShow:
    """`dbt-ci config show` reports the layer that set the command key."""

    def test_event_source(self, project):
        """A command key from the pull-request block is reported as from that event."""
        project(TestLayers.CONFIG)
        assert show(["delete"], PR_ENV) == (True, "event 'pull-request'")
        assert show(["ephemeral", "destroy", "--profile", "prod"], PR_ENV) == (
            True,
            "profile 'prod', event 'pull-request'",
        )
        assert show(["run"], PR_ENV) == (False, "default")

    def test_command_key_and_fallbacks(self, project):
        """The command key, the top-level key, the flag and the environment each show up."""
        project("dry-run: true\ndelete:\n  dry-run: false\n")
        assert show(["delete"]) == (False, "config file")
        assert show(["migration"]) == (True, "config file")
        assert show(["delete", "--dry-run"]) == (True, "command line")
        project("target: dev\n")
        assert show(["delete"], {"DBT_DRY_RUN": "true"}) == (True, "environment (DBT_DRY_RUN)")


class TestValidation:
    """The command keys are booleans, wherever they are written."""

    @pytest.mark.parametrize("section", ["delete", "migration", "ephemeral"])
    def test_non_boolean(self, section):
        """A string is rejected with the key's path."""
        assert validate_config({section: {"dry-run": "yes"}}) == [
            f"'{section}.dry-run' must be a boolean (true/false), got 'yes'"
        ]

    def test_in_an_event_block(self):
        """Event blocks are validated the same way."""
        errors = validate_config({"on": {"pull-request": {"delete": {"dry_run": 1}}}})
        assert errors == ["on.pull-request: 'delete.dry_run' must be a boolean (true/false), got 1"]

    def test_unknown_key_in_new_sections(self):
        """delete and migration only take dry-run."""
        assert validate_config({"delete": {"bogus": True}}) == ["Unknown key 'delete.bogus'"]

    def test_command_fails_on_a_bad_value(self, project):
        """The CLI refuses to run with a non-boolean command key."""
        project('delete:\n  dry-run: "yes"\n')
        result, args = invoke(("delete",))
        assert result.exit_code == 2
        assert "'delete.dry-run' must be a boolean" in result.output
        assert args is None
