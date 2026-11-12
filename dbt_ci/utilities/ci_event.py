"""
Tell whether a CI run is for a pull request, a push to the default branch or a schedule.

Config files can set values per event (`on: {pull-request: ..., push: ..., schedule: ...}`),
so a pull request can publish its state somewhere other than production. The event comes
from the variables each CI system sets:

- GitHub Actions: GITHUB_EVENT_NAME pull_request, pull_request_target or merge_group is
  a pull request; push is a push; schedule is a schedule.
- GitLab CI: CI_PIPELINE_SOURCE merge_request_event (or external_pull_request_event) is
  a pull request; push is a push; schedule is a schedule.
- Azure Pipelines: BUILD_REASON PullRequest is a pull request; IndividualCI and BatchedCI
  are pushes; Schedule is a schedule.
- Bitbucket Pipelines: BITBUCKET_PR_ID is set for pull requests; otherwise a push.
- CircleCI: CIRCLE_PULL_REQUEST is set for pull requests; otherwise a push.
- Buildkite: BUILDKITE_PULL_REQUEST is the PR number (not "false") for pull requests;
  BUILDKITE_SOURCE webhook is a push; schedule is a schedule.
- Jenkins (multibranch): CHANGE_ID is set for pull requests; otherwise a push.

A push only counts when it is to the default branch, so a push to a feature branch never
publishes production state. A schedule is a schedule whatever branch it runs on.
Bitbucket Pipelines, CircleCI and Jenkins set no variable that marks a scheduled run, so
there `--event schedule` names it. Anything else (a tag, a manual run, a local run, an
unknown CI) is no event, and only the settings outside `on:` apply. `--event`
(DBT_CI_EVENT) names the event explicitly, for CI systems not listed here.
"""

import json
import logging
import os
import subprocess
from dataclasses import dataclass
from typing import Mapping

logger = logging.getLogger(__name__)

PULL_REQUEST = "pull-request"
PUSH = "push"
SCHEDULE = "schedule"
EVENTS = (PULL_REQUEST, PUSH, SCHEDULE)


@dataclass(frozen=True)
class CiEvent:
    """The event a run is for (None when it is neither), and how that was decided."""

    name: str | None
    reason: str


def resolve_event(
    override: str | None,
    base_branch: str | None = None,
    env: Mapping[str, str] | None = None,
) -> CiEvent:
    """Return the event named by --event or DBT_CI_EVENT, or the one detected from CI."""
    env = os.environ if env is None else env
    override = override or env.get("DBT_CI_EVENT")
    if override:
        value = override.strip().lower()
        if value in EVENTS:
            return CiEvent(value, "set with --event / DBT_CI_EVENT")
        if value == "none":
            return CiEvent(None, "set to none with --event / DBT_CI_EVENT")
        raise ValueError(f"Unknown event '{override}'. Use pull-request, push, schedule or none.")
    return detect_event(base_branch, env)


def detect_event(base_branch: str | None = None, env: Mapping[str, str] | None = None) -> CiEvent:
    """Detect the event from the CI system's environment variables."""
    env = os.environ if env is None else env
    for detector in (
        _github,
        _gitlab,
        _azure,
        _bitbucket,
        _circleci,
        _buildkite,
        _jenkins,
    ):
        found = detector(env)
        if found is None:
            continue
        provider, kind, branch, default_branch = found
        if kind == PULL_REQUEST:
            return CiEvent(PULL_REQUEST, f"{provider} pull request")
        if kind == SCHEDULE:
            return CiEvent(SCHEDULE, f"{provider} scheduled run")
        if kind != PUSH or not branch:
            return CiEvent(None, f"{provider} run that is neither a pull request nor a push")
        default = base_branch or default_branch or _git_default_branch()
        if default is None:
            return CiEvent(
                None,
                f"{provider} push to '{branch}', but the default branch is unknown; pass "
                "--base-ref, or --event push",
            )
        if branch != default:
            return CiEvent(None, f"{provider} push to '{branch}', not the default branch")
        return CiEvent(PUSH, f"{provider} push to the default branch '{branch}'")
    return CiEvent(None, "no CI system detected")


# Each detector returns (provider, kind, pushed branch, default branch) for its CI system,
# or None when the run is not on it.
type Detected = tuple[str, str | None, str | None, str | None]


def _github(env: Mapping[str, str]) -> Detected | None:
    """GitHub Actions: the event name, and the default branch from the event payload."""
    if env.get("GITHUB_ACTIONS") != "true":
        return None
    event = env.get("GITHUB_EVENT_NAME", "")
    if event in ("pull_request", "pull_request_target", "merge_group"):
        return "GitHub Actions", PULL_REQUEST, None, None
    if event == "schedule":
        return "GitHub Actions", SCHEDULE, None, None
    if event != "push":
        return "GitHub Actions", None, None, None
    ref = env.get("GITHUB_REF", "")
    branch = ref.removeprefix("refs/heads/") if ref.startswith("refs/heads/") else None
    return "GitHub Actions", PUSH, branch, _github_default_branch(env)


def _github_default_branch(env: Mapping[str, str]) -> str | None:
    """Read the repository's default branch from the GitHub event payload."""
    path = env.get("GITHUB_EVENT_PATH")
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError):
        return None
    default = (payload.get("repository") or {}).get("default_branch")
    return default if isinstance(default, str) and default else None


def _gitlab(env: Mapping[str, str]) -> Detected | None:
    """GitLab CI: the pipeline source; CI_DEFAULT_BRANCH names the default branch."""
    if env.get("GITLAB_CI") != "true":
        return None
    source = env.get("CI_PIPELINE_SOURCE", "")
    default = env.get("CI_DEFAULT_BRANCH") or None
    if source in ("merge_request_event", "external_pull_request_event"):
        return "GitLab CI", PULL_REQUEST, None, default
    if source == "push":
        return "GitLab CI", PUSH, env.get("CI_COMMIT_BRANCH") or None, default
    if source == "schedule":
        return "GitLab CI", SCHEDULE, None, default
    return "GitLab CI", None, None, default


def _azure(env: Mapping[str, str]) -> Detected | None:
    """Azure Pipelines: the build reason; the branch comes from BUILD_SOURCEBRANCH."""
    if env.get("TF_BUILD", "").lower() != "true":
        return None
    reason = env.get("BUILD_REASON", "")
    if reason == "PullRequest":
        return "Azure Pipelines", PULL_REQUEST, None, None
    if reason == "Schedule":
        return "Azure Pipelines", SCHEDULE, None, None
    if reason in ("IndividualCI", "BatchedCI"):
        ref = env.get("BUILD_SOURCEBRANCH", "")
        branch = ref.removeprefix("refs/heads/") if ref.startswith("refs/heads/") else None
        return "Azure Pipelines", PUSH, branch, None
    return "Azure Pipelines", None, None, None


def _bitbucket(env: Mapping[str, str]) -> Detected | None:
    """Bitbucket Pipelines: pull request pipelines set BITBUCKET_PR_ID."""
    if not env.get("BITBUCKET_BUILD_NUMBER"):
        return None
    if env.get("BITBUCKET_PR_ID"):
        return "Bitbucket Pipelines", PULL_REQUEST, None, None
    return "Bitbucket Pipelines", PUSH, env.get("BITBUCKET_BRANCH") or None, None


def _circleci(env: Mapping[str, str]) -> Detected | None:
    """
    CircleCI: builds of a branch with an open pull request set CIRCLE_PULL_REQUEST.

    CircleCI has no environment variable for a scheduled pipeline (only the config-time
    pipeline values pipeline.trigger.type and pipeline.schedule.*), so a scheduled run
    reads as a push to its branch unless --event schedule names it.
    """
    if env.get("CIRCLECI") != "true":
        return None
    if env.get("CIRCLE_PULL_REQUEST"):
        return "CircleCI", PULL_REQUEST, None, None
    return "CircleCI", PUSH, env.get("CIRCLE_BRANCH") or None, None


def _buildkite(env: Mapping[str, str]) -> Detected | None:
    """Buildkite: BUILDKITE_PULL_REQUEST is the PR number, or "false"."""
    if env.get("BUILDKITE") != "true":
        return None
    default = env.get("BUILDKITE_PIPELINE_DEFAULT_BRANCH") or None
    if env.get("BUILDKITE_PULL_REQUEST", "false") not in ("", "false"):
        return "Buildkite", PULL_REQUEST, None, default
    if env.get("BUILDKITE_SOURCE") == "webhook":
        return "Buildkite", PUSH, env.get("BUILDKITE_BRANCH") or None, default
    if env.get("BUILDKITE_SOURCE") == "schedule":
        return "Buildkite", SCHEDULE, None, default
    return "Buildkite", None, None, default


def _jenkins(env: Mapping[str, str]) -> Detected | None:
    """Jenkins multibranch pipelines: pull request builds set CHANGE_ID."""
    if not env.get("JENKINS_URL"):
        return None
    if env.get("CHANGE_ID"):
        return "Jenkins", PULL_REQUEST, None, None
    return "Jenkins", PUSH, env.get("BRANCH_NAME") or None, None


def _git_default_branch() -> str | None:
    """Return the branch origin/HEAD points at, or None when git doesn't know it."""
    result = subprocess.run(
        ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
        capture_output=True,
        text=True,
    )
    ref = result.stdout.strip()
    if result.returncode != 0 or not ref:
        return None
    return ref.removeprefix("origin/")
