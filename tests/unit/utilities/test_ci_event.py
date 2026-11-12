"""Tests for telling pull request runs from pushes to the default branch, per CI system."""

import json
from unittest.mock import patch

import pytest

from dbt_ci.utilities.ci_event import PULL_REQUEST, PUSH, detect_event, resolve_event

GIT_DEFAULT = "dbt_ci.utilities.ci_event._git_default_branch"


@pytest.fixture(autouse=True)
def no_git_default():
    """Detection never asks the git repository the tests run in."""
    with patch(GIT_DEFAULT, return_value=None) as git_default:
        yield git_default


def github_payload(tmp_path, default_branch="main") -> str:
    """Write a GitHub event payload naming the default branch and return its path."""
    path = tmp_path / "event.json"
    path.write_text(json.dumps({"repository": {"default_branch": default_branch}}))
    return str(path)


@pytest.mark.parametrize(
    "env, expected",
    [
        # GitHub Actions
        ({"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "pull_request"}, PULL_REQUEST),
        ({"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "pull_request_target"}, PULL_REQUEST),
        ({"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "merge_group"}, PULL_REQUEST),
        ({"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "schedule"}, None),
        ({"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch"}, None),
        # GitLab CI
        ({"GITLAB_CI": "true", "CI_PIPELINE_SOURCE": "merge_request_event"}, PULL_REQUEST),
        (
            {
                "GITLAB_CI": "true",
                "CI_PIPELINE_SOURCE": "push",
                "CI_COMMIT_BRANCH": "main",
                "CI_DEFAULT_BRANCH": "main",
            },
            PUSH,
        ),
        (
            {
                "GITLAB_CI": "true",
                "CI_PIPELINE_SOURCE": "push",
                "CI_COMMIT_BRANCH": "feature",
                "CI_DEFAULT_BRANCH": "main",
            },
            None,
        ),
        ({"GITLAB_CI": "true", "CI_PIPELINE_SOURCE": "schedule"}, None),
        # Azure Pipelines
        ({"TF_BUILD": "True", "BUILD_REASON": "PullRequest"}, PULL_REQUEST),
        ({"TF_BUILD": "True", "BUILD_REASON": "Manual"}, None),
        # Bitbucket Pipelines
        ({"BITBUCKET_BUILD_NUMBER": "7", "BITBUCKET_PR_ID": "12"}, PULL_REQUEST),
        # CircleCI
        ({"CIRCLECI": "true", "CIRCLE_PULL_REQUEST": "https://x/pull/1"}, PULL_REQUEST),
        # Buildkite
        ({"BUILDKITE": "true", "BUILDKITE_PULL_REQUEST": "5"}, PULL_REQUEST),
        (
            {
                "BUILDKITE": "true",
                "BUILDKITE_PULL_REQUEST": "false",
                "BUILDKITE_SOURCE": "webhook",
                "BUILDKITE_BRANCH": "main",
                "BUILDKITE_PIPELINE_DEFAULT_BRANCH": "main",
            },
            PUSH,
        ),
        (
            {"BUILDKITE": "true", "BUILDKITE_PULL_REQUEST": "false", "BUILDKITE_SOURCE": "ui"},
            None,
        ),
        # Jenkins multibranch
        ({"JENKINS_URL": "https://ci", "CHANGE_ID": "3"}, PULL_REQUEST),
        # No CI at all
        ({}, None),
    ],
)
def test_detection_per_ci_system(env, expected):
    """Each CI system's own variables decide the event."""
    assert detect_event(env=env).name == expected


class TestPushes:
    """A push only counts when it is to the default branch."""

    def test_github_default_branch_from_the_event_payload(self, tmp_path):
        """GitHub names the default branch in the event payload; tags never count."""
        env = {
            "GITHUB_ACTIONS": "true",
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_EVENT_PATH": github_payload(tmp_path),
        }
        assert detect_event(env=env).name == PUSH
        assert detect_event(env={**env, "GITHUB_REF": "refs/heads/feature"}).name is None
        assert detect_event(env={**env, "GITHUB_REF": "refs/tags/v1.0.0"}).name is None

    @pytest.mark.parametrize(
        "env",
        [
            {
                "TF_BUILD": "True",
                "BUILD_REASON": "IndividualCI",
                "BUILD_SOURCEBRANCH": "refs/heads/main",
            },
            {"BITBUCKET_BUILD_NUMBER": "7", "BITBUCKET_BRANCH": "main"},
            {"CIRCLECI": "true", "CIRCLE_BRANCH": "main"},
            {"JENKINS_URL": "https://ci", "BRANCH_NAME": "main"},
        ],
    )
    def test_ci_systems_without_a_default_branch_variable(self, env, no_git_default):
        """Without a CI variable for it, --base-ref or git's origin/HEAD gives the default."""
        unknown = detect_event(env=env)
        assert unknown.name is None
        assert "default branch is unknown" in unknown.reason
        assert detect_event(base_branch="main", env=env).name == PUSH
        assert detect_event(base_branch="develop", env=env).name is None
        no_git_default.return_value = "main"
        assert detect_event(env=env).name == PUSH

    def test_base_ref_wins_over_the_ci_default(self, tmp_path):
        """A team deploying from another branch names it with --base-ref."""
        env = {
            "GITLAB_CI": "true",
            "CI_PIPELINE_SOURCE": "push",
            "CI_COMMIT_BRANCH": "release",
            "CI_DEFAULT_BRANCH": "main",
        }
        assert detect_event(env=env).name is None
        assert detect_event(base_branch="release", env=env).name == PUSH

    def test_reason_explains_the_decision(self):
        """The reason names the CI system and the branch."""
        env = {
            "GITLAB_CI": "true",
            "CI_PIPELINE_SOURCE": "push",
            "CI_COMMIT_BRANCH": "feature",
            "CI_DEFAULT_BRANCH": "main",
        }
        assert detect_event(env=env).reason == (
            "GitLab CI push to 'feature', not the default branch"
        )


class TestOverride:
    """--event (DBT_CI_EVENT) names the event explicitly."""

    def test_override_wins_over_detection(self):
        """An explicit event is used as given, and none switches event blocks off."""
        env = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "pull_request"}
        assert resolve_event("push", env=env).name == PUSH
        assert resolve_event("Pull-Request", env={}).name == PULL_REQUEST
        assert resolve_event("none", env=env).name is None
        assert resolve_event(None, env=env).name == PULL_REQUEST

    def test_unknown_event(self):
        """Anything else is an error naming the choices."""
        with pytest.raises(ValueError, match="pull-request, push or none"):
            resolve_event("deploy", env={})
