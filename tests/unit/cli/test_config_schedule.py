"""Tests for the `schedule` event's settings in the config file (`on: {schedule: ...}`)."""

import os
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from dbt_ci.cli.config.parser import normalize_event_keys
from dbt_ci.cli.config.schema import validate_config
from dbt_ci.commands.config.show import render_table, resolve_settings
from dbt_ci.main import cli

CONFIG = """
target: dev
on:
  pull-request:
    finalize:
      artifacts-uri: gs://bucket/prs/
  push:
    finalize:
      artifacts-uri: gs://bucket/dbt-state/
  schedule:
    notifications:
      format: compact
profiles:
  prod:
    target: production
    on:
      schedule:
        target: nightly
"""

SCHEDULE_ENV = {
    "GITHUB_ACTIONS": "true",
    "GITHUB_EVENT_NAME": "schedule",
    "GITHUB_REF": "refs/heads/feature",
}


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Run inside a directory with a schedule block and no CI variables set."""
    (tmp_path / "dbt-ci.config.yaml").write_text(CONFIG, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    for key in list(os.environ):
        if key.startswith(("DBT_", "GITHUB_", "GITLAB_", "CI_", "BUILDKITE", "TF_BUILD")):
            monkeypatch.delenv(key, raising=False)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setenv("DBT_CI_CACHE_DIR", str(cache_dir))
    return tmp_path


def finalize_args(cli_args=(), env=None):
    """Invoke finalize with its implementation stubbed and return its parsed arguments."""
    captured = {}
    # The config is also injected into os.environ; patch.dict drops it again afterwards
    with (
        patch.dict(os.environ),
        patch("dbt_ci.commands.finalize.cli.finalize", side_effect=lambda a: captured.update(a=a)),
    ):
        result = CliRunner().invoke(cli, ["finalize", *cli_args], env=env or {})
    assert result.exit_code in (0, None), result.output
    return captured["a"]


def settings(tokens, env):
    """Resolve settings as config show would, with the given CI variables."""
    with patch.dict(os.environ, env):
        resolved = resolve_settings(cli, tokens)
    return resolved, {s.option: (s.value, s.source) for s in resolved.settings}


class TestScheduleBlock:
    """A scheduled run gets the schedule settings, and only those."""

    @pytest.mark.parametrize(
        "env",
        [
            SCHEDULE_ENV,
            {"GITLAB_CI": "true", "CI_PIPELINE_SOURCE": "schedule", "CI_COMMIT_BRANCH": "main"},
            {"TF_BUILD": "True", "BUILD_REASON": "Schedule"},
            {"BUILDKITE": "true", "BUILDKITE_SOURCE": "schedule"},
        ],
    )
    def test_detected_schedule(self, project, env):
        """Each CI system's scheduled run applies the schedule block, not push's."""
        args = finalize_args(env=env)
        assert args.notifications_format == "compact"
        assert args.artifacts_uri is None
        assert args.target == "dev"

    def test_profile_schedule_block(self, project):
        """The profile's own schedule block goes over the top-level one."""
        args = finalize_args(["--profile", "prod"], env=SCHEDULE_ENV)
        assert args.target == "nightly"
        assert args.notifications_format == "compact"

    def test_explicit_event(self, project):
        """--event schedule and DBT_CI_EVENT=schedule name it on any CI system."""
        circleci = {"CIRCLECI": "true", "CIRCLE_BRANCH": "main"}
        assert finalize_args(["--event", "schedule"], env=circleci).notifications_format == (
            "compact"
        )
        args = finalize_args(env={"DBT_CI_EVENT": "schedule"})
        assert args.notifications_format == "compact"
        args = finalize_args(["--event", "none"], env=SCHEDULE_ENV)
        assert args.notifications_format == "default"

    def test_other_events_do_not_apply_it(self, project):
        """A pull request or a push leaves the schedule settings alone."""
        pull_request = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "pull_request"}
        assert finalize_args(env=pull_request).notifications_format == "default"
        assert finalize_args(["--event", "push"]).notifications_format == "default"

    def test_config_show(self, project):
        """config show names the scheduled run and the block that set each value."""
        resolved, by_option = settings(["finalize", "--profile", "prod"], SCHEDULE_ENV)
        assert (resolved.event, resolved.event_reason) == (
            "schedule",
            "GitHub Actions scheduled run",
        )
        assert by_option["--notifications-format"] == ("compact", "event 'schedule'")
        assert by_option["--target"] == ("nightly", "profile 'prod', event 'schedule'")
        assert "Event:       schedule (GitHub Actions scheduled run)" in render_table(
            resolved, show_all=False
        )


class TestScheduleValidation:
    """schedule is a valid event wherever `on:` is."""

    def test_valid_at_the_top_level_and_in_profiles(self):
        """Top level and profile schedule blocks validate like any other settings."""
        config = {
            "on": {"schedule": {"notifications": {"format": "compact"}}},
            "profiles": {"p": {"on": {"schedule": {"target": "nightly"}}}},
        }
        assert validate_config(config) == []

    def test_yaml_on_key_in_profiles(self):
        """A bare `on:` holding schedule is read as `on`, in profiles too."""
        raw = normalize_event_keys({"profiles": {"p": {True: {"schedule": {}}}}})
        assert validate_config(raw) == []

    def test_errors(self):
        """Bad keys and nested blocks inside schedule are reported with their path."""
        errors = validate_config(
            {"on": {"schedule": {"on": {}, "notifications": {"format": "loud"}}}}
        )
        assert "'on.schedule.on' is not allowed inside an event" in errors
        assert any(e.startswith("on.schedule: ") and "format" in e for e in errors), errors

    def test_json_schema_accepts_schedule(self):
        """The JSON schema lists schedule next to pull-request and push."""
        import json
        from pathlib import Path

        schema = json.loads(
            Path(__file__).parents[3].joinpath("dbt-ci.config.schema.json").read_text()
        )
        events = schema["properties"]["on"]["properties"]
        # schedule takes the same settings as pull-request (neither lists push branches)
        assert set(events) == {"pull-request", "push", "schedule"}
        assert events["schedule"] == events["pull-request"]
