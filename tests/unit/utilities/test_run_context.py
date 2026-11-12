"""Tests for the git and CI context init records in report.json."""

import json
import subprocess
import sys
from argparse import Namespace
from unittest.mock import patch

import click
import pytest

from dbt_ci.utilities.run_context import (
    ci_provider,
    collect_git_context,
    pull_request_base,
    repository,
    run_url,
)

SHA = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture(autouse=True)
def local_git():
    """Stand in for git, so a test only sees the variables it sets."""
    with (
        patch("dbt_ci.commands.finalize.publish_order.current_commit_sha", return_value=SHA),
        patch("dbt_ci.utilities.ci_event._git_current_branch", return_value=None),
        patch("dbt_ci.utilities.ci_event._git_default_branch", return_value=None),
    ):
        yield


def github_pr(tmp_path, number=42, head_sha="feedface" * 5):
    """Return the variables of a GitHub Actions pull request run, with its payload."""
    payload = tmp_path / "event.json"
    payload.write_text(json.dumps({"pull_request": {"number": number, "head": {"sha": head_sha}}}))
    return {
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_EVENT_PATH": str(payload),
        "GITHUB_REF": f"refs/pull/{number}/merge",
        "GITHUB_HEAD_REF": "feature/new-model",
        "GITHUB_BASE_REF": "main",
        "GITHUB_REPOSITORY": "acme/analytics",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_RUN_ID": "987",
    }


class TestCollectGitContext:
    """collect_git_context reads each CI system's variables, falling back to git."""

    def test_github_pull_request(self, tmp_path):
        """A GitHub pull request names its branches, head commit, number and run."""
        context = collect_git_context(Namespace(), env=github_pr(tmp_path))
        assert context == {
            "provider": "GitHub Actions",
            "repository": "acme/analytics",
            "event": "pull-request",
            "branch": "feature/new-model",
            "base_branch": "main",
            # The pull request's head, not the merge commit GitHub checks out
            "commit": "feedface" * 5,
            "pull_request": 42,
            "run_url": "https://github.com/acme/analytics/actions/runs/987",
        }

    def test_gitlab_merge_request(self):
        """A GitLab merge request reads the CI_MERGE_REQUEST_* variables."""
        env = {
            "GITLAB_CI": "true",
            "CI_PIPELINE_SOURCE": "merge_request_event",
            "CI_MERGE_REQUEST_IID": "7",
            "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME": "fix/orders",
            "CI_MERGE_REQUEST_TARGET_BRANCH_NAME": "develop",
            "CI_PROJECT_PATH": "acme/analytics",
            "CI_PIPELINE_URL": "https://gitlab.com/acme/analytics/-/pipelines/5",
        }
        context = collect_git_context(Namespace(), env=env)
        assert context["provider"] == "GitLab CI"
        assert context["event"] == "pull-request"
        assert (context["branch"], context["base_branch"]) == ("fix/orders", "develop")
        assert context["pull_request"] == 7
        assert context["commit"] == SHA
        assert context["run_url"] == "https://gitlab.com/acme/analytics/-/pipelines/5"

    def test_local_run(self):
        """A local run has no CI values, but still knows its commit."""
        context = collect_git_context(Namespace(), env={})
        assert context["provider"] is None
        assert context["event"] is None
        assert context["commit"] == SHA
        assert context["pull_request"] is None

    def test_base_ref_wins(self, tmp_path):
        """--base-ref names the base branch over the CI system's target branch."""
        context = collect_git_context(Namespace(base_ref="release"), env=github_pr(tmp_path))
        assert context["base_branch"] == "release"

    def test_event_override(self):
        """--event names the event, as it does for the config's on: blocks."""
        assert collect_git_context(Namespace(event="schedule"), env={})["event"] == "schedule"

    def test_event_the_config_was_resolved_for(self):
        """The event resolved for the config file wins, as it honours on.push.branches."""
        ctx = click.Context(click.Command("init"))
        ctx.meta["dbt_ci_event"] = ("push", "matches release/*")
        with ctx:
            assert collect_git_context(Namespace(), env={})["event"] == "push"

    def test_a_failing_value_is_none(self):
        """An error reading one value leaves it None instead of failing init."""
        with patch(
            "dbt_ci.commands.finalize.publish_order.current_commit_sha", side_effect=OSError("git")
        ):
            context = collect_git_context(Namespace(), env={})
        assert context["commit"] is None

    def test_bad_event_is_none(self):
        """An unknown --event is reported by the config parser; here it is just unknown."""
        assert collect_git_context(Namespace(event="nope"), env={})["event"] is None


class TestProviders:
    """Each CI system's name, repository, target branch and run link."""

    @pytest.mark.parametrize(
        "env, expected",
        [
            ({"GITHUB_ACTIONS": "true"}, "GitHub Actions"),
            ({"GITLAB_CI": "true"}, "GitLab CI"),
            ({"TF_BUILD": "True"}, "Azure Pipelines"),
            ({"BITBUCKET_BUILD_NUMBER": "3"}, "Bitbucket Pipelines"),
            ({"CIRCLECI": "true"}, "CircleCI"),
            ({"BUILDKITE": "true"}, "Buildkite"),
            ({"JENKINS_URL": "https://ci"}, "Jenkins"),
            ({}, None),
        ],
    )
    def test_provider(self, env, expected):
        """The provider is named after the CI system's marker variable."""
        assert ci_provider(env) == expected

    def test_circleci_repository(self):
        """CircleCI names the repository in two variables."""
        env = {
            "CIRCLECI": "true",
            "CIRCLE_PROJECT_USERNAME": "acme",
            "CIRCLE_PROJECT_REPONAME": "analytics",
        }
        assert repository(env) == "acme/analytics"

    def test_azure_target_branch_drops_refs_heads(self):
        """Azure names the target branch as a full ref."""
        assert pull_request_base({"SYSTEM_PULLREQUEST_TARGETBRANCH": "refs/heads/main"}) == "main"

    @pytest.mark.parametrize(
        "env, expected",
        [
            (
                {
                    "TF_BUILD": "true",
                    "SYSTEM_COLLECTIONURI": "https://dev.azure.com/acme/",
                    "SYSTEM_TEAMPROJECT": "data",
                    "BUILD_BUILDID": "12",
                },
                "https://dev.azure.com/acme/data/_build/results?buildId=12",
            ),
            (
                {
                    "BITBUCKET_BUILD_NUMBER": "4",
                    "BITBUCKET_GIT_HTTP_ORIGIN": "http://bitbucket.org/acme/analytics",
                },
                "http://bitbucket.org/acme/analytics/pipelines/results/4",
            ),
            ({"CIRCLECI": "true", "CIRCLE_BUILD_URL": "https://circle/1"}, "https://circle/1"),
            ({"BUILDKITE": "true", "BUILDKITE_BUILD_URL": "https://bk/2"}, "https://bk/2"),
            ({"JENKINS_URL": "https://ci", "BUILD_URL": "https://ci/job/3"}, "https://ci/job/3"),
            ({"GITHUB_ACTIONS": "true"}, None),
        ],
    )
    def test_run_url(self, env, expected):
        """Each CI system links to its run, or nothing when it doesn't say where."""
        assert run_url(env) == expected


def test_imports_on_its_own():
    """The module imports first, without dbt_ci.commands loaded (no circular import)."""
    result = subprocess.run(
        [sys.executable, "-c", "import dbt_ci.utilities.run_context"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
