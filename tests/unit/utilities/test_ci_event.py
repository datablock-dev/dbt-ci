"""Tests for telling pull request runs from pushes to the default branch, per CI system."""

import json
from unittest.mock import MagicMock, patch

import pytest

from dbt_ci.utilities.ci_event import (
    _git_current_branch,
    PULL_REQUEST,
    PUSH,
    current_branch,
    detect_event,
    pull_request_number,
    resolve_event,
)

GIT_DEFAULT = "dbt_ci.utilities.ci_event._git_default_branch"
GIT_BRANCH = "dbt_ci.utilities.ci_event._git_current_branch"
# The real function, kept before the autouse fixture below patches it for every test
real_git_current_branch = _git_current_branch


@pytest.fixture(autouse=True)
def no_git_default():
    """Detection never asks the git repository the tests run in."""
    with patch(GIT_DEFAULT, return_value=None) as git_default:
        yield git_default


@pytest.fixture(autouse=True)
def no_git_branch():
    """Branch resolution never reads the branch the tests run on."""
    with patch(GIT_BRANCH, return_value=None) as git_branch:
        yield git_branch


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


class TestPullRequestNumber:
    """{pr} comes from the pull request variable of each CI system."""

    @pytest.mark.parametrize(
        "env, expected",
        [
            # GitHub Actions: the ref when there is no payload
            ({"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/pull/42/merge"}, 42),
            ({"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/main"}, None),
            # GitHub merge queue (merge_group): the number is in the queue branch
            (
                {
                    "GITHUB_ACTIONS": "true",
                    "GITHUB_REF": "refs/heads/gh-readonly-queue/main/pr-18-0123abcd",
                },
                18,
            ),
            # GitLab CI
            ({"GITLAB_CI": "true", "CI_MERGE_REQUEST_IID": "7"}, 7),
            ({"GITLAB_CI": "true", "CI_EXTERNAL_PULL_REQUEST_IID": "8"}, 8),
            ({"GITLAB_CI": "true", "CI_PIPELINE_SOURCE": "push"}, None),
            # Azure Pipelines: the number (GitHub repos) wins over the ID (Azure Repos)
            (
                {
                    "TF_BUILD": "True",
                    "SYSTEM_PULLREQUEST_PULLREQUESTNUMBER": "15",
                    "SYSTEM_PULLREQUEST_PULLREQUESTID": "9001",
                },
                15,
            ),
            ({"TF_BUILD": "True", "SYSTEM_PULLREQUEST_PULLREQUESTID": "9001"}, 9001),
            # Bitbucket Pipelines
            ({"BITBUCKET_BUILD_NUMBER": "3", "BITBUCKET_PR_ID": "12"}, 12),
            ({"BITBUCKET_BUILD_NUMBER": "3"}, None),
            # CircleCI: the number at the end of the pull request URL
            (
                {
                    "CIRCLECI": "true",
                    "CIRCLE_PULL_REQUEST": "https://github.com/org/repo/pull/123",
                },
                123,
            ),
            ({"CIRCLECI": "true", "CIRCLE_PULL_REQUEST": "https://x/pull/8/"}, 8),
            ({"CIRCLECI": "true", "CIRCLE_PULL_REQUEST": "https://x/pull/abc"}, None),
            # Buildkite: "false" outside pull requests
            ({"BUILDKITE": "true", "BUILDKITE_PULL_REQUEST": "5"}, 5),
            ({"BUILDKITE": "true", "BUILDKITE_PULL_REQUEST": "false"}, None),
            # Jenkins multibranch
            ({"JENKINS_URL": "https://ci", "CHANGE_ID": "31"}, 31),
            ({"JENKINS_URL": "https://ci", "BRANCH_NAME": "main"}, None),
            # A variable without its CI system's own marker is not read
            ({"CHANGE_ID": "31", "BITBUCKET_PR_ID": "12"}, None),
            ({}, None),
        ],
    )
    def test_per_ci_system(self, env, expected):
        """Each CI system names the number in its own variable."""
        assert pull_request_number(env) == expected

    def test_github_event_payload(self, tmp_path):
        """GitHub's event payload wins over the ref, e.g. for pull_request_target."""
        path = tmp_path / "event.json"
        path.write_text(json.dumps({"pull_request": {"number": 77}}))
        env = {
            "GITHUB_ACTIONS": "true",
            "GITHUB_EVENT_PATH": str(path),
            "GITHUB_REF": "refs/heads/main",
        }
        assert pull_request_number(env) == 77

    def test_github_unreadable_payload_falls_back_to_the_ref(self, tmp_path):
        """A payload that can't be read leaves the ref to decide."""
        path = tmp_path / "event.json"
        path.write_text("not json")
        env = {
            "GITHUB_ACTIONS": "true",
            "GITHUB_EVENT_PATH": str(path),
            "GITHUB_REF": "refs/pull/9/head",
        }
        assert pull_request_number(env) == 9


class TestCurrentBranch:
    """{branch} is a pull request's source branch, else the branch the CI system built."""

    @pytest.mark.parametrize(
        "env, expected",
        [
            # GitHub Actions
            (
                {
                    "GITHUB_ACTIONS": "true",
                    "GITHUB_HEAD_REF": "feature/x",
                    "GITHUB_REF": "refs/pull/1/merge",
                },
                "feature/x",
            ),
            ({"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/main"}, "main"),
            ({"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/tags/v1"}, None),
            # GitLab CI
            (
                {
                    "GITLAB_CI": "true",
                    "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME": "feature/x",
                    "CI_COMMIT_BRANCH": "ignored",
                },
                "feature/x",
            ),
            (
                {
                    "GITLAB_CI": "true",
                    "CI_EXTERNAL_PULL_REQUEST_SOURCE_BRANCH_NAME": "ext",
                },
                "ext",
            ),
            ({"GITLAB_CI": "true", "CI_COMMIT_BRANCH": "main"}, "main"),
            # Azure Pipelines: refs/heads/ is dropped; a pull request's own ref is not a branch
            (
                {
                    "TF_BUILD": "True",
                    "SYSTEM_PULLREQUEST_SOURCEBRANCH": "refs/heads/users/a/fix",
                    "BUILD_SOURCEBRANCH": "refs/pull/4/merge",
                },
                "users/a/fix",
            ),
            ({"TF_BUILD": "True", "SYSTEM_PULLREQUEST_SOURCEBRANCH": "feature"}, "feature"),
            ({"TF_BUILD": "True", "BUILD_SOURCEBRANCH": "refs/heads/main"}, "main"),
            ({"TF_BUILD": "True", "BUILD_SOURCEBRANCH": "refs/tags/v1"}, None),
            # Bitbucket Pipelines, CircleCI, Buildkite
            ({"BITBUCKET_BUILD_NUMBER": "3", "BITBUCKET_BRANCH": "feature"}, "feature"),
            ({"CIRCLECI": "true", "CIRCLE_BRANCH": "feature"}, "feature"),
            ({"BUILDKITE": "true", "BUILDKITE_BRANCH": "feature"}, "feature"),
            # Jenkins: CHANGE_BRANCH for pull requests, whose BRANCH_NAME is PR-<n>
            (
                {"JENKINS_URL": "https://ci", "CHANGE_BRANCH": "feature", "BRANCH_NAME": "PR-3"},
                "feature",
            ),
            ({"JENKINS_URL": "https://ci", "BRANCH_NAME": "main"}, "main"),
            ({}, None),
        ],
    )
    def test_per_ci_system(self, env, expected):
        """Each CI system names the branch in its own variables."""
        assert current_branch(env) == expected

    def test_git_fallback(self, no_git_branch):
        """Without a CI branch variable, the branch git has checked out is used."""
        no_git_branch.return_value = "local-branch"
        assert current_branch({}) == "local-branch"
        assert current_branch({"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/tags/v1"}) == (
            "local-branch"
        )
        assert current_branch({"CIRCLECI": "true", "CIRCLE_BRANCH": "ci"}) == "ci"


class TestGitCurrentBranch:
    """git's checked-out branch, but never a detached HEAD."""

    @pytest.mark.parametrize(
        "returncode, stdout, expected",
        [(0, "feature/x\n", "feature/x"), (0, "HEAD\n", None), (128, "", None)],
    )
    def test_reads_git(self, returncode, stdout, expected):
        """A detached HEAD or a failed git call gives no branch."""
        result = MagicMock(returncode=returncode, stdout=stdout)
        with patch("dbt_ci.utilities.ci_event.subprocess.run", return_value=result) as run:
            assert real_git_current_branch() == expected
        run.assert_called_once()
        assert run.call_args[0][0] == ["git", "rev-parse", "--abbrev-ref", "HEAD"]
