"""Post the dbt-ci report as a pull request comment on GitHub."""
import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# Hidden marker that identifies the comment dbt-ci owns, so later runs edit it in place
COMMENT_MARKER = "<!-- dbt-ci-report -->"

# GitHub rejects comment bodies longer than this many characters
GITHUB_COMMENT_LIMIT = 65536

# Comments are listed this many at a time while looking for the existing report
PAGE_SIZE = 100


class GitHubAPIError(Exception):
    """Raised when a GitHub API request fails."""


def resolve_pull_request() -> tuple[str, int] | None:
    """
    Return the repository and pull request number of the current GitHub Actions run.

    The number is read from the event payload of pull_request events and falls back to
    GITHUB_REF (refs/pull/<n>/merge). Runs that are not for a pull request return None.
    """
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not repository:
        return None

    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if event_path and os.path.isfile(event_path):
        try:
            with open(event_path, encoding="utf-8") as f:
                event = json.load(f)
            number = (event.get("pull_request") or {}).get("number")
            if isinstance(number, int):
                return repository, number
        except (OSError, ValueError) as e:
            logger.debug(f"Could not read the GitHub event payload at {event_path}: {e}")

    match = re.fullmatch(r"refs/pull/(\d+)/(?:merge|head)", os.environ.get("GITHUB_REF", ""))
    if match:
        return repository, int(match.group(1))
    return None


def build_comment_body(markdown: str) -> str:
    """Prefix the report with the marker and cut it to GitHub's comment size limit."""
    body = f"{COMMENT_MARKER}\n{markdown}"
    if len(body) <= GITHUB_COMMENT_LIMIT:
        return body
    note = "\n\n_The report was cut to fit GitHub's comment size limit. The job summary has the full report._\n"
    return body[: GITHUB_COMMENT_LIMIT - len(note)] + note


class GitHubClient:
    """Minimal GitHub REST client for reading and writing issue comments."""

    def __init__(self, token: str, api_url: str | None = None):
        self.token = token
        self.api_url = (api_url or os.environ.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/")

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        """Send one API request and return the decoded JSON response."""
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.api_url}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "dbt-ci",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
        except urllib.error.HTTPError as e:
            raise GitHubAPIError(f"{method} {path} returned {e.code}: {e.read().decode('utf-8', 'replace')[:300]}") from e
        except urllib.error.URLError as e:
            raise GitHubAPIError(f"{method} {path} failed: {e.reason}") from e
        return json.loads(body) if body else None

    def find_report_comment(self, repository: str, number: int) -> int | None:
        """Return the id of the comment carrying the dbt-ci marker, if there is one."""
        page = 1
        while True:
            comments = self.request(
                "GET", f"/repos/{repository}/issues/{number}/comments?per_page={PAGE_SIZE}&page={page}"
            ) or []
            for comment in comments:
                if (comment.get("body") or "").startswith(COMMENT_MARKER):
                    return comment["id"]
            if len(comments) < PAGE_SIZE:
                return None
            page += 1

    def upsert_report_comment(self, repository: str, number: int, body: str) -> str:
        """Update the existing report comment or create one, returning "updated" or "created"."""
        comment_id = self.find_report_comment(repository, number)
        if comment_id is not None:
            self.request("PATCH", f"/repos/{repository}/issues/comments/{comment_id}", {"body": body})
            return "updated"
        self.request("POST", f"/repos/{repository}/issues/{number}/comments", {"body": body})
        return "created"


def post_pr_comment(markdown: str) -> bool:
    """
    Post or update the report comment on the current pull request.

    Never raises: a run outside a pull request, a missing token or a rejected request
    (e.g. the read-only token of a pull request from a fork) is logged and skipped, so
    the comment can never fail the CI job. Returns whether the comment was written.
    """
    pull_request = resolve_pull_request()
    if pull_request is None:
        logger.info("Not running for a GitHub pull request; skipping the PR comment.")
        return False

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        logger.warning(
            "No GITHUB_TOKEN set; skipping the PR comment. Pass it to the step with "
            "'env: GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}' and grant 'pull-requests: write'."
        )
        return False

    repository, number = pull_request
    try:
        action = GitHubClient(token).upsert_report_comment(repository, number, build_comment_body(markdown))
    except GitHubAPIError as e:
        logger.warning(f"Could not post the report to {repository}#{number}: {e}")
        return False

    logger.info(f"Report comment {action} on {repository}#{number}.")
    return True
