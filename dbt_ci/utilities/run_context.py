"""
Collect the git and CI context of a run, which init records in report.json.

The report then says which branch, commit and pull request a run was for, against
which base branch, on which CI system, and links to the CI run. Every value is read
from the variables the CI system sets, falling back to git, and is None when neither
knows it. Collecting it never fails the command.
"""

import logging
import os
from argparse import Namespace
from typing import Any, Mapping

import click

from dbt_ci.cli.config.parser import config_event
from dbt_ci.commands.finalize.publish_order import current_commit_sha
from dbt_ci.utilities.ci_event import (
    _github_payload,
    current_branch,
    pull_request_number,
    resolve_event,
)

logger = logging.getLogger(__name__)


def collect_git_context(args: Namespace, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Return the run's provider, event, branch, base branch, commit, pull request and run URL."""
    env = os.environ if env is None else env
    context: dict[str, Any] = {}
    steps = (
        ("provider", lambda: ci_provider(env)),
        ("repository", lambda: repository(env)),
        ("event", lambda: event_name(args, env)),
        ("branch", lambda: current_branch(env)),
        ("base_branch", lambda: getattr(args, "base_ref", None) or pull_request_base(env)),
        ("commit", lambda: head_commit(env)),
        ("pull_request", lambda: pull_request_number(env)),
        ("run_url", lambda: run_url(env)),
    )
    for key, read in steps:
        try:
            context[key] = read()
        except Exception as e:  # The context is informational; init must not fail on it
            logger.debug(f"Could not tell the run's {key}: {e}")
            context[key] = None
    return context


def ci_provider(env: Mapping[str, str]) -> str | None:
    """Return the name of the CI system the run is on, or None for a local run."""
    if env.get("GITHUB_ACTIONS") == "true":
        return "GitHub Actions"
    if env.get("GITLAB_CI") == "true":
        return "GitLab CI"
    if env.get("TF_BUILD", "").lower() == "true":
        return "Azure Pipelines"
    if env.get("BITBUCKET_BUILD_NUMBER"):
        return "Bitbucket Pipelines"
    if env.get("CIRCLECI") == "true":
        return "CircleCI"
    if env.get("BUILDKITE") == "true":
        return "Buildkite"
    if env.get("JENKINS_URL"):
        return "Jenkins"
    return None


def repository(env: Mapping[str, str]) -> str | None:
    """Return the repository the run is for, as the CI system names it."""
    if env.get("CIRCLECI") == "true" and env.get("CIRCLE_PROJECT_REPONAME"):
        return f"{env.get('CIRCLE_PROJECT_USERNAME')}/{env['CIRCLE_PROJECT_REPONAME']}"
    for name in (
        "GITHUB_REPOSITORY",
        "CI_PROJECT_PATH",
        "BUILD_REPOSITORY_NAME",
        "BITBUCKET_REPO_FULL_NAME",
        "BUILDKITE_REPO",
    ):
        if env.get(name):
            return env[name]
    return None


def event_name(args: Namespace, env: Mapping[str, str]) -> str | None:
    """
    Return the event the run is for: pull-request, push, schedule or None.

    The event the config file's `on:` blocks were resolved for wins, since it also
    honours `on.push.branches`; otherwise it is resolved the same way.
    """
    resolved = config_event(click.get_current_context(silent=True))
    if resolved is not None:
        return resolved[0]
    return resolve_event(
        getattr(args, "event", None), base_branch=getattr(args, "base_ref", None), env=env
    ).name


def pull_request_base(env: Mapping[str, str]) -> str | None:
    """Return the branch a pull request merges into, from the CI system's variables."""
    for name in (
        "GITHUB_BASE_REF",
        "CI_MERGE_REQUEST_TARGET_BRANCH_NAME",
        "CI_EXTERNAL_PULL_REQUEST_TARGET_BRANCH_NAME",
        "SYSTEM_PULLREQUEST_TARGETBRANCH",
        "BITBUCKET_PR_DESTINATION_BRANCH",
        "BUILDKITE_PULL_REQUEST_BASE_BRANCH",
        "CHANGE_TARGET",
    ):
        value = env.get(name, "").strip()
        if value:
            return value.removeprefix("refs/heads/")
    return None


def head_commit(env: Mapping[str, str]) -> str | None:
    """
    Return the commit the run is for.

    On a GitHub pull request that is the head of the pull request, not the merge commit
    GitHub checks out to test it; elsewhere the checked-out commit.
    """
    if env.get("GITHUB_ACTIONS") == "true":
        sha = ((_github_payload(env).get("pull_request") or {}).get("head") or {}).get("sha")
        if isinstance(sha, str) and sha:
            return sha
    return current_commit_sha()


def run_url(env: Mapping[str, str]) -> str | None:
    """Return a link to the CI run, when the CI system says where it is."""
    if env.get("GITHUB_ACTIONS") == "true":
        server, repo, run = (
            env.get("GITHUB_SERVER_URL", "https://github.com"),
            env.get("GITHUB_REPOSITORY"),
            env.get("GITHUB_RUN_ID"),
        )
        return f"{server}/{repo}/actions/runs/{run}" if repo and run else None
    if env.get("TF_BUILD", "").lower() == "true":
        collection, project, build = (
            env.get("SYSTEM_COLLECTIONURI"),
            env.get("SYSTEM_TEAMPROJECT"),
            env.get("BUILD_BUILDID"),
        )
        if collection and project and build:
            return f"{collection.rstrip('/')}/{project}/_build/results?buildId={build}"
        return None
    if env.get("BITBUCKET_BUILD_NUMBER"):
        origin = env.get("BITBUCKET_GIT_HTTP_ORIGIN")
        return f"{origin}/pipelines/results/{env['BITBUCKET_BUILD_NUMBER']}" if origin else None
    for name in ("CI_PIPELINE_URL", "CIRCLE_BUILD_URL", "BUILDKITE_BUILD_URL", "BUILD_URL"):
        if env.get(name):
            return env[name]
    return None
