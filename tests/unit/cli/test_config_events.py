"""Tests for per-event settings in the config file (`on: {pull-request: ..., push: ...}`)."""

import json
import os
from pathlib import Path
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


class TestDefaultBranch:
    """The default branch a push must be to comes from --base-ref, the config, or init."""

    def env(self, project, branch="release"):
        """A GitHub push to `release`, with main as the repository default."""
        return push_env(project, branch)

    def test_base_ref_flag(self, project, monkeypatch):
        """--base-ref on the command line names the deploy branch."""
        monkeypatch.setattr("sys.argv", ["dbt-ci", "finalize", "--base-ref", "release"])
        _, by_option = settings(["finalize"], self.env(project))
        assert by_option["--artifacts-uri"][1] == "event 'push'"

    def test_recorded_by_init(self, project):
        """Commands after init use the base ref init recorded."""
        cache = {"config": {"reference": {"base_ref": "release"}}}
        (project / "cache" / "cache.json").write_text(json.dumps(cache))
        resolved, _ = settings(["finalize"], self.env(project))
        assert resolved.event == "push"

    def test_without_one_the_repository_default_counts(self, project):
        """Without any of them, a push to release is not a push to the default branch."""
        resolved, _ = settings(["finalize"], self.env(project))
        assert resolved.event is None


BRANCHES_CONFIG = """
target: dev
on:
  push:
    branches:
      - main
      - release/*
    finalize:
      artifacts-uri: gs://bucket/dbt-state/
profiles:
  staging:
    on:
      push:
        branches: develop
        target: staging
  plain:
    target: plain
"""


@pytest.fixture
def branches_project(project):
    """The project fixture, with a config that lists push branches."""
    (project / "dbt-ci.config.yaml").write_text(BRANCHES_CONFIG, encoding="utf-8")
    return project


class TestPushBranches:
    """on.push.branches names the branches a push deploys from."""

    def test_pattern_match(self, branches_project):
        """A push to a branch matching a pattern applies the push block."""
        args = finalize_args(env=push_env(branches_project, "release/1.2"))
        assert args.artifacts_uri == "gs://bucket/dbt-state/"
        assert finalize_args(env=push_env(branches_project)).artifacts_uri == (
            "gs://bucket/dbt-state/"
        )

    def test_no_match(self, branches_project):
        """Feature branch pushes are still ignored."""
        args = finalize_args(env=push_env(branches_project, "feature/x"))
        assert args.artifacts_uri is None
        assert args.target == "dev"

    def test_branches_is_not_a_setting(self, branches_project):
        """The list decides the event only; it is never passed on as DBT_BRANCHES."""
        resolved, _ = settings(["finalize"], push_env(branches_project, "release/1.2"))
        assert "DBT_BRANCHES" not in os.environ
        assert all("BRANCHES" not in s.option.upper() for s in resolved.settings)

    def test_config_show_reason(self, branches_project):
        """config show explains which pattern the branch matched."""
        resolved, by_option = settings(["finalize"], push_env(branches_project, "release/1.2"))
        assert resolved.event == "push"
        assert resolved.event_reason == "GitHub Actions push to 'release/1.2' (matches release/*)"
        assert by_option["--artifacts-uri"] == ("gs://bucket/dbt-state/", "event 'push'")
        resolved, _ = settings(["finalize"], push_env(branches_project, "feature/x"))
        assert resolved.event is None
        assert resolved.event_reason == (
            "GitHub Actions push to 'feature/x', not one of the push branches (main, release/*)"
        )

    def test_profile_list_replaces_the_top_level_list(self, branches_project):
        """A profile's own branches (here a single string) replace the top-level ones."""
        args = finalize_args(["--profile", "staging"], env=push_env(branches_project, "develop"))
        # The top-level push block still applies once the event is push, then the profile's
        assert args.artifacts_uri == "gs://bucket/dbt-state/"
        assert args.target == "staging"
        args = finalize_args(["--profile", "staging"], env=push_env(branches_project, "main"))
        assert args.artifacts_uri is None
        assert args.target == "dev"

    def test_profile_without_a_list_inherits_the_top_level_one(self, branches_project):
        """A profile without its own branches uses the top-level list."""
        args = finalize_args(["--profile", "plain"], env=push_env(branches_project, "release/2"))
        assert args.artifacts_uri == "gs://bucket/dbt-state/"

    def test_unknown_default_branch_does_not_block(self, branches_project):
        """With branches listed, the push is detected without any default-branch info."""
        env = {**push_env(branches_project, "release/1.2"), "GITHUB_EVENT_PATH": ""}
        with patch("dbt_ci.utilities.ci_event._git_default_branch", return_value=None) as git:
            resolved, _ = settings(["finalize"], env)
        assert resolved.event == "push"
        git.assert_not_called()

    def test_env_refs_are_resolved(self, project):
        """${VAR} references in the list are resolved; an empty result counts as not set."""
        (project / "dbt-ci.config.yaml").write_text(
            "on:\n  push:\n    branches: ${DEPLOY_BRANCH}\n    target: prod\n", encoding="utf-8"
        )
        resolved, _ = settings(["finalize"], {**push_env(project, "env"), "DEPLOY_BRANCH": "env"})
        assert resolved.event == "push"
        # Empty: back to the default-branch rule
        resolved, _ = settings(["finalize"], {**push_env(project), "DEPLOY_BRANCH": ""})
        assert resolved.event == "push"
        resolved, _ = settings(["finalize"], {**push_env(project, "env"), "DEPLOY_BRANCH": ""})
        assert resolved.event is None

    def test_without_branches_the_default_branch_rule_stays(self, project):
        """The original config, without branches, still only counts the default branch."""
        assert settings(["finalize"], push_env(project))[0].event_reason == (
            "GitHub Actions push to the default branch 'main'"
        )
        assert settings(["finalize"], push_env(project, "release/1.2"))[0].event is None


class TestPushBranchesValidation:
    """branches is only valid in a push block, as a name, a pattern or a list of them."""

    @pytest.mark.parametrize(
        "config",
        [
            {"on": {"push": {"branches": ["main", "release/*"]}}},
            {"on": {"push": {"branches": "main"}}},
            {"profiles": {"p": {"on": {"push": {"branches": ["develop"], "target": "x"}}}}},
        ],
    )
    def test_valid(self, config):
        """A string or a list of strings is accepted, in a profile too."""
        assert validate_config(config) == []

    def test_rejected_in_pull_request(self):
        """A pull-request block has no branches, with a clear message (and no 'unknown key')."""
        errors = validate_config({"on": {"pull-request": {"branches": ["main"]}}})
        assert errors == [
            "'on.pull-request.branches' is only allowed under push: it lists the branches a "
            "push deploys from"
        ]
        errors = validate_config({"profiles": {"p": {"on": {"pull-request": {"branches": "x"}}}}})
        assert errors == [
            "profiles.p: 'on.pull-request.branches' is only allowed under push: it lists the "
            "branches a push deploys from"
        ]

    def test_rejected_outside_on(self):
        """branches is not a top-level or profile setting."""
        assert validate_config({"branches": ["main"]}) == ["Unknown key 'branches'"]
        assert validate_config({"profiles": {"p": {"branches": "main"}}}) == [
            "profiles.p: Unknown key 'branches'"
        ]

    @pytest.mark.parametrize(
        "value, error",
        [
            ([], "'on.push.branches' must be a branch name or pattern, or a list of them, got []"),
            (3, "'on.push.branches' must be a branch name or pattern, or a list of them, got 3"),
            ({"a": 1}, "'on.push.branches' must be a branch name or pattern, or a list of them"),
            (["main", 3], "'on.push.branches' items must be non-empty strings, got 3"),
            ([""], "'on.push.branches' items must be non-empty strings, got ''"),
            (None, "'on.push.branches' must be a branch name or pattern, or a list of them"),
        ],
    )
    def test_bad_values(self, value, error):
        """Anything but a non-empty string or list of them is an error."""
        errors = validate_config({"on": {"push": {"branches": value}}})
        assert len(errors) == 1 and errors[0].startswith(error)

    def test_json_schema(self):
        """The editor schema accepts branches under push only."""
        jsonschema = pytest.importorskip("jsonschema")
        schema = json.loads(
            Path(__file__).parents[3].joinpath("dbt-ci.config.schema.json").read_text()
        )
        validator = jsonschema.Draft7Validator(schema)

        def valid(config):
            """Return whether the JSON schema accepts a config."""
            return validator.is_valid(config)

        assert valid({"on": {"push": {"branches": ["main", "release/*"]}}})
        assert valid({"on": {"push": {"branches": "main"}}})
        assert valid({"profiles": {"p": {"on": {"push": {"branches": "develop"}}}}})
        assert not valid({"on": {"push": {"branches": []}}})
        assert not valid({"on": {"push": {"branches": [3]}}})
        assert not valid({"on": {"pull-request": {"branches": ["main"]}}})
        assert not valid({"profiles": {"p": {"branches": ["main"]}}})
