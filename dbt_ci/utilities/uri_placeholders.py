"""
Fill in the `{pr}` and `{branch}` placeholders of `finalize --artifacts-uri`.

So every pull request can publish to a folder of its own instead of overwriting the
others, e.g. `gs://my-bucket/dbt-ci-prs/{pr}/`:

- `{pr}` is the number of the pull or merge request the run is for
  (see `ci_event.pull_request_number`).
- `{branch}` is the branch the run is for: a pull request's source branch, else the
  branch the CI system built, else the branch git has checked out
  (see `ci_event.current_branch`). It is made safe as one path segment by
  `path_segment`.

A placeholder that can't be resolved is an error: uploading to a literal `{pr}` folder
would mix every pull request together again. `{sha}` is refused rather than filled in:
it marks the commit in the per-commit manifest copies finalize already keeps at
`<artifacts-uri>/<commit>/manifest.json`, which init looks up as merge-base baselines,
so a second meaning would only make it easy to write into that layout by accident.
"""

import logging
import re
from typing import Callable, Mapping

from dbt_ci.errors import ConfigurationError
from dbt_ci.utilities.ci_event import current_branch, pull_request_number

logger = logging.getLogger(__name__)

PR_PLACEHOLDER = "{pr}"
BRANCH_PLACEHOLDER = "{branch}"
SUPPORTED = (PR_PLACEHOLDER, BRANCH_PLACEHOLDER)

# A `{name}` token; braces around anything with a slash are not taken for a placeholder
PLACEHOLDER_PATTERN = re.compile(r"\{[^{}/]*\}")

# Characters kept as they are in a branch's path segment; any run of others becomes "-"
UNSAFE_SEGMENT_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def reject_uri_placeholders(uri: str | None, option: str) -> None:
    """
    Raise ConfigurationError when a URI that doesn't support them has `{pr}` or `{branch}`.

    Only finalize --artifacts-uri fills them in; anywhere else they would be read as a
    literal folder name.
    """
    found = [token for token in SUPPORTED if uri and token in uri]
    if found:
        raise ConfigurationError(
            f"{option} '{uri}' contains {' and '.join(found)}, which only "
            "finalize --artifacts-uri fills in. Give it the location without placeholders."
        )


def path_segment(branch: str) -> str:
    """
    Make a branch name safe as one storage path segment.

    Every run of characters other than ASCII letters, digits, `.`, `_` and `-` becomes a
    single `-`, and leading or trailing `-` and `.` are dropped, so
    `feature/DBT-12 fix` becomes `feature-DBT-12-fix`. Case is kept.
    """
    return UNSAFE_SEGMENT_CHARS.sub("-", branch).strip("-.")


def resolve_uri_placeholders(
    uri: str, option: str = "--artifacts-uri", env: Mapping[str, str] | None = None
) -> str:
    """
    Return the URI with `{pr}` and `{branch}` filled in for this run.

    A URI without placeholders is returned unchanged. Raises ConfigurationError for a
    placeholder that can't be resolved, `{sha}`, or one dbt-ci doesn't know.
    """
    tokens = set(PLACEHOLDER_PATTERN.findall(uri))
    if not tokens:
        return uri
    unknown = sorted(tokens - set(SUPPORTED))
    if "{sha}" in unknown:
        raise ConfigurationError(
            f"{option} '{uri}' contains {{sha}}, which is not supported there: finalize "
            "already keeps a copy of the manifest for each commit at "
            "<artifacts-uri>/<commit>/manifest.json. Use {pr} or {branch} instead."
        )
    if unknown:
        raise ConfigurationError(
            f"{option} '{uri}' contains the unknown placeholder(s) {', '.join(unknown)}. "
            f"Supported placeholders are {' and '.join(SUPPORTED)}."
        )

    resolvers: dict[str, Callable[[], str | None]] = {
        PR_PLACEHOLDER: lambda: _pull_request(env),
        BRANCH_PLACEHOLDER: lambda: _branch(env),
    }
    resolved = uri
    for token in sorted(tokens):
        value = resolvers[token]()
        if not value:
            raise ConfigurationError(f"Cannot resolve {token} in {option} '{uri}': {_why(token)}")
        resolved = resolved.replace(token, value)
    logger.info(f"Resolved {option} {uri} to {resolved}")
    return resolved


def _pull_request(env: Mapping[str, str] | None) -> str | None:
    """Return the pull request number as text, or None when the run has none."""
    number = pull_request_number(env)
    return str(number) if number is not None else None


def _branch(env: Mapping[str, str] | None) -> str | None:
    """Return the run's branch as a path segment, or None when it is unknown."""
    branch = current_branch(env)
    return path_segment(branch) if branch else None


def _why(token: str) -> str:
    """Explain why a placeholder could not be resolved and what to do about it."""
    if token == PR_PLACEHOLDER:
        return (
            "this run is not for a pull request, or its CI system is not one dbt-ci reads "
            "the number from (GitHub Actions, GitLab CI, Azure Pipelines, Bitbucket "
            "Pipelines, CircleCI, Buildkite, Jenkins). Set the URI under "
            "'on: pull-request:' so other runs don't use it, or put the number in the "
            "URI yourself."
        )
    return (
        "no CI branch variable is set and git's HEAD is detached, or the branch name has "
        "no characters usable in a path. Put the branch in the URI yourself, or use {pr}."
    )
