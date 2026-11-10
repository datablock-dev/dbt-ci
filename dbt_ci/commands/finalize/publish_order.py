"""
Keep finalize from replacing the published manifest with an older commit's.

Two deploys can finish out of order: a queued or re-run deploy of an older commit ends
after the deploy of a newer one, and its upload would put the older state back as the
latest. Next to `manifest.json`, finalize records the commit it was built from in
`manifest.commit.json`, and before replacing it checks that the published commit is not
newer than its own:

- git decides when it can: if this commit is an ancestor of the published one, the
  published manifest is newer and is kept; if the published commit is an ancestor of
  this one, this manifest is newer.
- Otherwise (the published commit is missing from a shallow clone, or the two diverged)
  the commit times decide.
- Without a record or a known commit there is nothing to compare, so the upload goes
  ahead as before.

Two deploys finishing at the same moment can still race between the check and the
upload; serialize deploy jobs (e.g. a GitHub Actions `concurrency` group) for that.
"""

import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone

from dbt_ci.schema import StorageConnectorConfig

logger = logging.getLogger(__name__)

COMMIT_RECORD = "manifest.commit.json"

# Commit SHAs CI systems expose, for runs without a usable git checkout
CI_COMMIT_SHA_VARS = ("GITHUB_SHA", "CI_COMMIT_SHA", "BUILDKITE_COMMIT", "CIRCLE_SHA1")

# Seconds to wait for git to fetch the published commit before falling back to times
FETCH_TIMEOUT = 120


@dataclass(frozen=True)
class Commit:
    """A commit a manifest was built from, with its committer time when known."""

    sha: str
    committed_at: int | None = None


def current_commit_sha() -> str | None:
    """Return the checked-out commit's full SHA, from git or the CI environment."""
    result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
    sha = result.stdout.strip() if result.returncode == 0 else ""
    if not sha:
        sha = next((os.environ[name] for name in CI_COMMIT_SHA_VARS if os.environ.get(name)), "")
    return sha or None


def commit_time(sha: str) -> int | None:
    """Return a commit's committer time as a Unix timestamp, or None if git lacks it."""
    result = subprocess.run(
        ["git", "show", "-s", "--format=%ct", sha], capture_output=True, text=True
    )
    value = result.stdout.strip()
    return int(value) if result.returncode == 0 and value.isdigit() else None


def commit_record(commit: Commit | None) -> dict:
    """Return the record uploaded next to manifest.json; a null commit disables the check."""
    return {
        "commit": commit.sha if commit else None,
        "committed_at": commit.committed_at if commit else None,
        "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def read_published_commit(artifacts_uri: str, connector: StorageConnectorConfig) -> Commit | None:
    """Return the commit the published manifest was built from, or None if unrecorded."""
    uri = f"{artifacts_uri}/{COMMIT_RECORD}"
    try:
        if uri not in connector["list"](uri):
            return None
        record = connector["download"](uri)
    except Exception as e:
        logger.warning(f"Could not read {uri}, so the published manifest's commit is unknown: {e}")
        return None
    sha = record.get("commit") if isinstance(record, dict) else None
    if not isinstance(sha, str) or not sha:
        return None
    committed_at = record.get("committed_at")
    return Commit(sha, committed_at if isinstance(committed_at, int) else None)


def published_is_newer(ours: Commit, published: Commit) -> bool:
    """Report whether the published manifest comes from a newer commit than ours."""
    if ours.sha == published.sha:
        return False
    if not _has_commit(published.sha):
        _fetch(published.sha)
    if _is_ancestor(ours.sha, published.sha):
        return True
    if _is_ancestor(published.sha, ours.sha):
        return False
    # Unrelated in the history git has: diverged, or cut off by a shallow clone
    if ours.committed_at is None or published.committed_at is None:
        return False
    return published.committed_at > ours.committed_at


def _has_commit(sha: str) -> bool:
    """Report whether the local repository has a commit."""
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True, text=True
    )
    return result.returncode == 0


def _fetch(sha: str) -> None:
    """Fetch a commit (and its history down to what is already here) from origin."""
    try:
        result = subprocess.run(
            ["git", "fetch", "--quiet", "origin", sha],
            capture_output=True,
            text=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            timeout=FETCH_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.debug(f"Fetching {sha[:12]} timed out.")
        return
    if result.returncode != 0:
        logger.debug(f"Could not fetch {sha[:12]}: {result.stderr.strip()}")


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    """Report whether git knows `ancestor` to be an ancestor of `descendant`."""
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0
