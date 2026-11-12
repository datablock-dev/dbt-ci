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


class TestPushBranches:
    """With push branches, a push counts when its branch matches one of them."""

    def env(self, branch, tmp_path=None):
        """A GitHub push to a branch, with main as the default branch when tmp_path is given."""
        env = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "push"}
        env["GITHUB_REF"] = f"refs/heads/{branch}"
        if tmp_path is not None:
            env["GITHUB_EVENT_PATH"] = github_payload(tmp_path)
        return env

    @pytest.mark.parametrize(
        "branch, pattern",
        [
            ("main", "main"),
            ("release/1.2", "release/*"),
            # fnmatch: `*` matches `/` too
            ("release/1.2/hotfix", "release/*"),
            ("hotfix-7", "hotfix-?"),
        ],
    )
    def test_patterns(self, tmp_path, branch, pattern):
        """Names and fnmatch patterns match, and the reason names the pattern."""
        event = detect_event(
            env=self.env(branch, tmp_path), push_branches=["main", "release/*", "hotfix-?"]
        )
        assert event.name == PUSH
        assert event.reason == f"GitHub Actions push to '{branch}' (matches {pattern})"

    def test_no_match(self, tmp_path):
        """A feature branch push is still no event, even when it is the default branch."""
        patterns = ["main", "release/*"]
        event = detect_event(env=self.env("feature/x", tmp_path), push_branches=patterns)
        assert event.name is None
        assert event.reason == (
            "GitHub Actions push to 'feature/x', not one of the push branches (main, release/*)"
        )
        # The list replaces the default-branch rule: main is not implied
        assert detect_event(env=self.env("main", tmp_path), push_branches=["develop"]).name is None
        # Matching is case-sensitive
        assert detect_event(env=self.env("Main", tmp_path), push_branches=["main"]).name is None

    def test_tags_never_count(self, tmp_path):
        """A tag push is not a branch push, whatever the patterns."""
        env = {**self.env("main", tmp_path), "GITHUB_REF": "refs/tags/v1.0.0"}
        assert detect_event(env=env, push_branches=["*"]).name is None

    @pytest.mark.parametrize(
        "env",
        [
            {
                "TF_BUILD": "True",
                "BUILD_REASON": "IndividualCI",
                "BUILD_SOURCEBRANCH": "refs/heads/develop",
            },
            {"BITBUCKET_BUILD_NUMBER": "7", "BITBUCKET_BRANCH": "develop"},
            {"CIRCLECI": "true", "CIRCLE_BRANCH": "develop"},
            {"JENKINS_URL": "https://ci", "BRANCH_NAME": "develop"},
            {
                "GITHUB_ACTIONS": "true",
                "GITHUB_EVENT_NAME": "push",
                "GITHUB_REF": "refs/heads/develop",
            },
        ],
    )
    def test_unknown_default_branch_does_not_block(self, env, no_git_default):
        """No default branch is needed, so git is not asked and the push still counts."""
        assert detect_event(env=env).name is None
        no_git_default.reset_mock()
        assert detect_event(env=env, push_branches=["develop"]).name == PUSH
        no_git_default.assert_not_called()

    def test_base_ref_does_not_widen_the_list(self):
        """With push branches, --base-ref no longer decides which pushes count."""
        env = {
            "GITLAB_CI": "true",
            "CI_PIPELINE_SOURCE": "push",
            "CI_COMMIT_BRANCH": "main",
            "CI_DEFAULT_BRANCH": "main",
        }
        assert detect_event(base_branch="main", env=env, push_branches=["release/*"]).name is None

    def test_without_branches_the_default_branch_rule_stays(self, tmp_path):
        """No list (or an empty one) keeps the default-branch rule."""
        for push_branches in (None, []):
            assert detect_event(
                env=self.env("main", tmp_path), push_branches=push_branches
            ).name == (PUSH)
            assert (
                detect_event(env=self.env("release/1", tmp_path), push_branches=push_branches).name
                is None
            )

    def test_override_ignores_the_list(self):
        """--event push names the event whatever branch is pushed."""
        env = self.env("feature")
        assert resolve_event("push", env=env, push_branches=["main"]).name == PUSH
        assert resolve_event(None, env=env, push_branches=["feature"]).name == PUSH
