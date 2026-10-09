"""Unit tests for posting the report as a GitHub pull request comment."""
import io
import json
import logging
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from dbt_ci.notifications.github import (
    COMMENT_MARKER,
    GITHUB_COMMENT_LIMIT,
    PAGE_SIZE,
    build_comment_body,
    post_pr_comment,
    resolve_pull_request,
)

GITHUB_VARIABLES = (
    "GITHUB_REPOSITORY", "GITHUB_EVENT_PATH", "GITHUB_REF", "GITHUB_TOKEN", "GH_TOKEN", "GITHUB_API_URL",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Start every test without the runner's own GitHub Actions variables."""
    for key in GITHUB_VARIABLES:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def pull_request_env(monkeypatch):
    """Simulate a pull_request run on org/repo#7 with a token."""
    monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
    monkeypatch.setenv("GITHUB_REF", "refs/pull/7/merge")
    monkeypatch.setenv("GITHUB_TOKEN", "token")


def response(payload) -> MagicMock:
    """Build a urlopen context manager returning a JSON payload."""
    mock = MagicMock()
    mock.__enter__.return_value.read.return_value = json.dumps(payload).encode("utf-8")
    return mock


def requests_made(urlopen: MagicMock) -> list[tuple[str, str, dict | None]]:
    """Return (method, url, payload) for every request sent through urlopen."""
    calls = []
    for call in urlopen.call_args_list:
        request = call.args[0]
        payload = json.loads(request.data) if request.data else None
        calls.append((request.get_method(), request.full_url, payload))
    return calls


class TestResolvePullRequest:
    """Test how the pull request of the current run is found."""

    def test_from_event_payload(self, monkeypatch, tmp_path):
        """pull_request events carry the number in the event payload."""
        event = tmp_path / "event.json"
        event.write_text(json.dumps({"pull_request": {"number": 42}}), encoding="utf-8")
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
        assert resolve_pull_request() == ("org/repo", 42)

    def test_from_ref(self, monkeypatch):
        """Without a pull_request payload the number is read from GITHUB_REF."""
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
        monkeypatch.setenv("GITHUB_REF", "refs/pull/13/merge")
        assert resolve_pull_request() == ("org/repo", 13)

    def test_push_event_is_not_a_pull_request(self, monkeypatch, tmp_path):
        """A push to a branch has no pull request to comment on."""
        event = tmp_path / "event.json"
        event.write_text(json.dumps({"ref": "refs/heads/main"}), encoding="utf-8")
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
        monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
        assert resolve_pull_request() is None

    def test_outside_github_actions(self):
        """Without GITHUB_REPOSITORY there is nothing to resolve."""
        assert resolve_pull_request() is None


class TestBuildCommentBody:
    """Test the comment body sent to GitHub."""

    def test_starts_with_marker(self):
        """The marker comes first so later runs can find the comment."""
        assert build_comment_body("## report").startswith(f"{COMMENT_MARKER}\n## report")

    def test_long_reports_are_cut_to_the_limit(self):
        """Bodies over GitHub's limit are cut, with a note pointing at the job summary."""
        body = build_comment_body("x" * (GITHUB_COMMENT_LIMIT * 2))
        assert len(body) <= GITHUB_COMMENT_LIMIT
        assert "job summary" in body


class TestPostPrComment:
    """Test creating and updating the report comment."""

    def test_creates_comment_when_none_exists(self, pull_request_env):
        """The first run posts a new comment."""
        with patch("urllib.request.urlopen", side_effect=[response([]), response({})]) as urlopen:
            assert post_pr_comment("## report") is True
        calls = requests_made(urlopen)
        assert calls[0][:2] == ("GET", f"https://api.github.com/repos/org/repo/issues/7/comments?per_page={PAGE_SIZE}&page=1")
        assert calls[1][:2] == ("POST", "https://api.github.com/repos/org/repo/issues/7/comments")
        assert calls[1][2]["body"].startswith(COMMENT_MARKER)

    def test_updates_existing_comment(self, pull_request_env):
        """Later runs edit the comment carrying the marker, even past the first page."""
        first_page = [{"id": i, "body": "unrelated"} for i in range(PAGE_SIZE)]
        second_page = [{"id": 999, "body": f"{COMMENT_MARKER}\nold report"}]
        with patch(
            "urllib.request.urlopen", side_effect=[response(first_page), response(second_page), response({})]
        ) as urlopen:
            assert post_pr_comment("## new report") is True
        method, url, payload = requests_made(urlopen)[-1]
        assert (method, url) == ("PATCH", "https://api.github.com/repos/org/repo/issues/comments/999")
        assert "new report" in payload["body"]

    def test_uses_github_api_url(self, pull_request_env, monkeypatch):
        """GitHub Enterprise runs use the API address Actions provides."""
        monkeypatch.setenv("GITHUB_API_URL", "https://ghe.example/api/v3")
        with patch("urllib.request.urlopen", side_effect=[response([]), response({})]) as urlopen:
            post_pr_comment("## report")
        assert requests_made(urlopen)[0][1].startswith("https://ghe.example/api/v3/repos/org/repo/")

    def test_skips_outside_a_pull_request(self, monkeypatch):
        """A push run makes no request at all."""
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
        monkeypatch.setenv("GITHUB_TOKEN", "token")
        with patch("urllib.request.urlopen") as urlopen:
            assert post_pr_comment("## report") is False
        urlopen.assert_not_called()

    def test_skips_without_token(self, pull_request_env, monkeypatch, caplog):
        """A missing token is a warning that explains how to provide one."""
        monkeypatch.delenv("GITHUB_TOKEN")
        with patch("urllib.request.urlopen") as urlopen, caplog.at_level(logging.WARNING):
            assert post_pr_comment("## report") is False
        urlopen.assert_not_called()
        assert "GITHUB_TOKEN" in caplog.text

    def test_api_errors_do_not_raise(self, pull_request_env, caplog):
        """A rejected request (e.g. a fork's read-only token) is logged, not raised."""
        error = urllib.error.HTTPError("url", 403, "Forbidden", {}, io.BytesIO(b'{"message": "Resource not accessible"}'))
        with patch("urllib.request.urlopen", side_effect=error), caplog.at_level(logging.WARNING):
            assert post_pr_comment("## report") is False
        assert "403" in caplog.text
