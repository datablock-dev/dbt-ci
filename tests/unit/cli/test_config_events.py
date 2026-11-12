"""Tests for per-event settings in the config file (`on: {pull-request: ..., push: ...}`)."""

import json
import os
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from dbt_ci.cli.config.parser import normalize_event_keys
from dbt_ci.cli.config.schema import validate_config
from dbt_ci.commands.config.show import resolve_settings
from dbt_ci.main import cli

CONFIG = """
target: dev
finalize:
  files: [manifest]
on:
  pull-request:
    finalize:
      artifacts-uri: gs://bucket/prs/
  push:
    target: prod
    finalize:
      artifacts-uri: gs://bucket/dbt-state/
profiles:
  prod:
    target: production
    on:
      push:
        finalize:
          files: [manifest, cache]
"""

PR_ENV = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "pull_request"}


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Run inside a directory with an event-scoped config and no CI variables set."""
    (tmp_path / "dbt-ci.config.yaml").write_text(CONFIG, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    for key in list(os.environ):
        if key.startswith(("DBT_", "GITHUB_", "GITLAB_", "CI_", "BUILDKITE")):
            monkeypatch.delenv(key, raising=False)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setenv("DBT_CI_CACHE_DIR", str(cache_dir))
    payload = tmp_path / "event.json"
    payload.write_text(json.dumps({"repository": {"default_branch": "main"}}))
    return tmp_path


def push_env(project, branch="main") -> dict:
    """GitHub Actions variables for a push to a branch."""
    return {
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": f"refs/heads/{branch}",
        "GITHUB_EVENT_PATH": str(project / "event.json"),
    }


def finalize_args(cli_args=(), env=None):
    """Invoke finalize with its implementation stubbed and return its parsed arguments."""
    captured = {}
    with patch("dbt_ci.commands.finalize.cli.finalize", side_effect=lambda a: captured.update(a=a)):
        result = CliRunner().invoke(cli, ["finalize", *cli_args], env=env or {})
    assert result.exit_code in (0, None), result.output
    return captured["a"]


def settings(tokens, env):
    """Resolve settings as config show would, with the given CI variables."""
    with patch.dict(os.environ, env):
        resolved = resolve_settings(cli, tokens)
    return resolved, {s.option: (s.value, s.source) for s in resolved.settings}


class TestEventBlocks:
    """The block for the detected event goes over the profile and the top level."""

    def test_pull_request(self, project):
        """A pull request run gets the pull-request settings."""
        args = finalize_args(env=PR_ENV)
        assert args.artifacts_uri == "gs://bucket/prs/"
        assert args.target == "dev"

    def test_push_to_the_default_branch(self, project):
        """A push to main gets the push settings, top level and profile."""
        args = finalize_args(env=push_env(project))
        assert args.artifacts_uri == "gs://bucket/dbt-state/"
        assert args.target == "prod"
        args = finalize_args(["--profile", "prod"], env=push_env(project))
        # The top-level push block goes over the profile, then the profile's own block
        assert args.target == "prod"
        assert list(args.files) == ["manifest", "cache"]

    def test_push_to_a_feature_branch_applies_no_block(self, project):
        """Only the default branch counts as a push."""
        args = finalize_args(env=push_env(project, "feature"))
        assert args.artifacts_uri is None
        assert args.target == "dev"

    def test_explicit_event(self, project):
        """--event and DBT_CI_EVENT override detection; none applies no block."""
        assert finalize_args(["--event", "push"]).artifacts_uri == "gs://bucket/dbt-state/"
        assert finalize_args(env={"DBT_CI_EVENT": "pull-request"}).artifacts_uri == (
            "gs://bucket/prs/"
        )
        assert finalize_args(["--event", "none"], env=PR_ENV).artifacts_uri is None

    def test_command_line_still_wins(self, project):
        """A flag beats the event block."""
        args = finalize_args(["--artifacts-uri", "gs://other/"], env=PR_ENV)
        assert args.artifacts_uri == "gs://other/"

    def test_config_show_names_the_event_and_source(self, project):
        """config show reports the event, why, and which block set each value."""
        resolved, by_option = settings(["finalize", "--profile", "prod"], push_env(project))
        assert resolved.event == "push"
        assert resolved.event_reason == "GitHub Actions push to the default branch 'main'"
        assert by_option["--artifacts-uri"] == ("gs://bucket/dbt-state/", "event 'push'")
        assert by_option["--files"] == (("manifest", "cache"), "profile 'prod', event 'push'")


class TestValidation:
    """Event blocks are validated like the top level."""

    def test_yaml_on_key(self):
        """PyYAML reads `on:` as the boolean true; it is renamed back, in profiles too."""
        raw = normalize_event_keys({True: {"push": {}}, "profiles": {"p": {True: {}}}})
        assert "on" in raw and "on" in raw["profiles"]["p"]

    def test_errors(self):
        """Unknown events, nested blocks and bad keys are reported with their path."""
        errors = validate_config(
            {
                "on": {
                    "deploy": {},
                    "push": {"profiles": {}, "finalize": {"bogus": 1}},
                }
            }
        )
        assert "Unknown event 'on.deploy': use pull-request or push" in errors
        assert "'on.push.profiles' is not allowed inside an event" in errors
        assert "on.push: Unknown key 'finalize.bogus'" in errors

    def test_valid_in_profiles(self):
        """A profile can have its own event blocks."""
        assert validate_config({"profiles": {"p": {"on": {"push": {"target": "x"}}}}}) == []
