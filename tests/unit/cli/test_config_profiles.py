"""Tests for config file profiles selected with --profile."""

import json
import os
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from dbt_ci.cli.config.schema import validate_config
from dbt_ci.main import cli

CONFIG = """
target: dev
runner: bash
init:
  reference-target: production
  comparison-strategy: hybrid
  state-uri: gs://bucket/top/manifest.json
docker:
  volumes:
    - a:/a
    - b:/b
profiles:
  action:
    target: ci
    init:
      comparison_strategy: dbt
      state-uri: gs://bucket/action/manifest.json
    docker:
      volumes:
        - c:/c
  sandbox:
    DBT_TARGET: sandbox
  empty:
"""

INIT = "dbt_ci.commands.init.cli.init"
RUN = "dbt_ci.commands.run.cli.run"


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Run inside a directory with a profiled config file and an empty cache directory."""
    (tmp_path / "dbt-ci.config.yaml").write_text(CONFIG, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    # The config loader injects values via os.environ.setdefault; keep runs independent.
    for key in list(os.environ):
        if key.startswith("DBT_"):
            monkeypatch.delenv(key, raising=False)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setenv("DBT_CI_CACHE_DIR", str(cache_dir))
    return tmp_path


def invoke(target: str, cli_args=(), env=None):
    """Invoke a command with its implementation stubbed, returning (result, args)."""
    captured = {}

    def capture(args):
        captured["args"] = args

    command = "init" if target == INIT else "run"
    with patch(target, side_effect=capture):
        result = CliRunner().invoke(cli, [command, *cli_args], env=env or {})
    return result, captured.get("args")


def resolved(target: str, cli_args=(), env=None):
    """Invoke a command and return its parsed arguments, failing on an error exit."""
    result, args = invoke(target, cli_args, env)
    assert result.exit_code in (0, None), result.output
    return args


def record_profile(project, profile):
    """Write a cache.json as init would, recording the given profile."""
    cache = {"config": {"profile": profile}}
    (project / "cache" / "cache.json").write_text(json.dumps(cache), encoding="utf-8")


class TestProfileSelection:
    """Test how a selected profile combines with the top-level settings."""

    def test_no_profile_uses_top_level_settings(self, project):
        """Without --profile the file behaves as it always has."""
        args = resolved(INIT)
        assert args.target == "dev"
        assert args.comparison_strategy == "hybrid"
        assert args.state_uri == "gs://bucket/top/manifest.json"
        assert args.profile is None

    def test_profile_overrides_top_level(self, project):
        """The profile's values win; settings it leaves out come from the top level."""
        args = resolved(INIT, ["--profile", "action"])
        assert args.target == "ci"
        assert args.comparison_strategy == "dbt"
        assert args.state_uri == "gs://bucket/action/manifest.json"
        assert args.reference_target == "production"
        assert args.runner == "bash"
        assert args.profile == "action"

    def test_profile_list_replaces_top_level_list(self, project):
        """A profile's list is the complete list, not an addition."""
        args = resolved(INIT, ["--profile", "action"])
        assert list(args.docker_volumes) == ["c:/c"]

    def test_profile_given_before_config(self, project):
        """Click runs eager options in command-line order; either order works."""
        args = resolved(INIT, ["--profile", "action", "--config", "dbt-ci.config.yaml"])
        assert args.target == "ci"
        args = resolved(INIT, ["--config", "dbt-ci.config.yaml", "--profile", "action"])
        assert args.target == "ci"

    def test_profile_from_environment(self, project):
        """DBT_CI_PROFILE selects a profile."""
        assert resolved(INIT, env={"DBT_CI_PROFILE": "action"}).target == "ci"

    def test_legacy_flat_keys_in_a_profile(self, project):
        """A profile may use the flat DBT_* style, overriding a nested top-level key."""
        assert resolved(INIT, ["--profile", "sandbox"]).target == "sandbox"

    def test_empty_profile(self, project):
        """A profile with no settings applies the top-level ones."""
        assert resolved(INIT, ["--profile", "empty"]).target == "dev"

    def test_cli_flag_beats_profile(self, project):
        """An explicit flag still wins over the selected profile."""
        args = resolved(INIT, ["--profile", "action", "--target", "local"])
        assert args.target == "local"

    def test_profile_on_a_subcommand(self, project):
        """`ephemeral destroy --profile` applies the profile, not what the group resolved."""
        captured = {}
        with (
            patch(
                "dbt_ci.commands.ephemeral.cli.destroy",
                side_effect=lambda a: captured.update(args=a),
            ),
            patch("dbt_ci.commands.ephemeral.cli.CacheManager"),
        ):
            result = CliRunner().invoke(cli, ["ephemeral", "destroy", "--profile", "action"])
        assert result.exit_code in (0, None), result.output
        assert captured["args"].target == "ci"

    def test_unknown_profile_fails(self, project):
        """A typo fails and lists the profiles that exist."""
        result, _ = invoke(INIT, ["--profile", "acton"])
        assert result.exit_code == 2
        assert "Available profiles: action, empty, sandbox" in result.output

    def test_profile_without_config_file_fails(self, tmp_path, monkeypatch):
        """Asking for a profile without a config file is an error, not a silent no-op."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("DBT_CI_CACHE_DIR", str(tmp_path))
        result, _ = invoke(INIT, ["--profile", "action"])
        assert result.exit_code == 2
        assert "no dbt-ci config file was found" in result.output


class TestInheritanceFromInit:
    """Test that later commands reuse the profile init ran with."""

    def test_run_inherits_profile(self, project):
        """run applies the profile recorded in init's cache."""
        record_profile(project, "action")
        args = resolved(RUN)
        assert args.target == "ci"
        assert args.profile == "action"

    def test_explicit_profile_beats_inherited(self, project):
        """--profile on a later command wins over the recorded one."""
        record_profile(project, "action")
        assert resolved(RUN, ["--profile", "sandbox"]).target == "sandbox"

    def test_init_does_not_inherit(self, project):
        """init starts a new run, so it ignores the previous run's profile."""
        record_profile(project, "action")
        assert resolved(INIT).target == "dev"

    def test_recorded_profile_missing_from_file_is_ignored(self, project):
        """A recorded profile that no longer exists falls back to the top level."""
        record_profile(project, "gone")
        args = resolved(RUN)
        assert args.target == "dev"


class TestProfileValidation:
    """Test that profiles are validated like the top level."""

    def test_valid_profiles(self):
        """Profiles take the same keys as the top level."""
        config = {
            "profiles": {
                "ci": {"target": "ci", "init": {"state-uri": "gs://b/m.json"}},
                "empty": None,
            }
        }
        assert validate_config(config) == []

    def test_invalid_value_in_profile(self):
        """Errors inside a profile name the profile."""
        errors = validate_config({"profiles": {"ci": {"runner": "kubernetes"}}})
        assert any(e.startswith("profiles.ci:") and "runner" in e for e in errors)

    def test_unknown_key_in_profile(self):
        """Unknown keys are rejected inside profiles too."""
        assert validate_config({"profiles": {"ci": {"nope": 1}}})

    def test_nested_profiles_are_rejected(self):
        """A profile cannot contain profiles."""
        errors = validate_config({"profiles": {"ci": {"profiles": {"x": {}}}}})
        assert any("cannot be nested" in e for e in errors)

    def test_profiles_must_be_a_mapping(self):
        """A list of names (without settings) is rejected."""
        assert validate_config({"profiles": ["ci", "sandbox"]})
