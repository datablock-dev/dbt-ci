"""Tests for the {pr} and {branch} placeholders of finalize --artifacts-uri."""

from unittest.mock import patch

import pytest

from dbt_ci.errors import ConfigurationError
from dbt_ci.utilities.uri_placeholders import (
    path_segment,
    reject_uri_placeholders,
    resolve_uri_placeholders,
)

GITHUB_PR = {
    "GITHUB_ACTIONS": "true",
    "GITHUB_EVENT_NAME": "pull_request",
    "GITHUB_REF": "refs/pull/42/merge",
    "GITHUB_HEAD_REF": "feature/DBT-12-new-model",
}
GITHUB_PUSH = {"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/main"}


@pytest.fixture(autouse=True)
def no_git_branch():
    """Resolution never reads the branch the tests run on."""
    with patch("dbt_ci.utilities.ci_event._git_current_branch", return_value=None) as git:
        yield git


class TestPathSegment:
    """A branch name becomes one safe storage path segment."""

    @pytest.mark.parametrize(
        "branch, expected",
        [
            ("main", "main"),
            ("feature/DBT-12", "feature-DBT-12"),
            ("users/ana/fix #3", "users-ana-fix-3"),
            ("release_1.2", "release_1.2"),
            ("owner:branch", "owner-branch"),
            ("a//b", "a-b"),
            ("feature/ö", "feature"),
            ("-dash.", "dash"),
            ("///", ""),
        ],
    )
    def test_sanitising(self, branch, expected):
        """Runs of other characters become one "-", and the ends lose "-" and "."."""
        assert path_segment(branch) == expected


class TestResolve:
    """Placeholders are filled in for the run, or fail it."""

    def test_no_placeholders_is_unchanged(self):
        """A URI without placeholders needs nothing from the environment."""
        assert resolve_uri_placeholders("gs://b/dbt-state/", env={}) == "gs://b/dbt-state/"

    def test_pull_request_and_branch(self):
        """{pr} is the number, {branch} the sanitised source branch."""
        assert resolve_uri_placeholders("gs://b/prs/{pr}/", env=GITHUB_PR) == "gs://b/prs/42/"
        assert (
            resolve_uri_placeholders("s3://b/{branch}/pr-{pr}", env=GITHUB_PR)
            == "s3://b/feature-DBT-12-new-model/pr-42"
        )

    def test_repeated_placeholder(self):
        """Every occurrence is replaced."""
        assert resolve_uri_placeholders("gs://b/{pr}/{pr}", env=GITHUB_PR) == "gs://b/42/42"

    def test_branch_of_a_push(self):
        """A push resolves {branch} to the pushed branch."""
        assert resolve_uri_placeholders("gs://b/{branch}/", env=GITHUB_PUSH) == "gs://b/main/"

    def test_branch_from_git(self, no_git_branch):
        """Outside CI, {branch} is the branch git has checked out."""
        no_git_branch.return_value = "feat/local"
        assert resolve_uri_placeholders("gs://b/{branch}", env={}) == "gs://b/feat-local"

    def test_unresolved_pull_request_fails(self):
        """A push has no pull request number: an error, not a literal {pr} folder."""
        with pytest.raises(ConfigurationError, match=r"Cannot resolve \{pr\} in --artifacts-uri"):
            resolve_uri_placeholders("gs://b/prs/{pr}/", env=GITHUB_PUSH)

    def test_unresolved_branch_fails(self):
        """No CI branch and a detached HEAD: an error."""
        with pytest.raises(ConfigurationError, match=r"Cannot resolve \{branch\}"):
            resolve_uri_placeholders("gs://b/{branch}/", env={})

    def test_branch_with_nothing_safe_left_fails(self, no_git_branch):
        """A branch that sanitises to nothing can't name a folder."""
        no_git_branch.return_value = "///"
        with pytest.raises(ConfigurationError, match=r"Cannot resolve \{branch\}"):
            resolve_uri_placeholders("gs://b/{branch}/", env={})

    def test_sha_is_refused(self):
        """{sha} is the per-commit copies' marker, so it is refused with the reason."""
        with pytest.raises(ConfigurationError, match="already keeps a copy"):
            resolve_uri_placeholders("gs://b/{sha}/", env=GITHUB_PR)

    def test_unknown_placeholder_is_refused(self):
        """A typo is reported with the placeholders that exist."""
        with pytest.raises(ConfigurationError, match=r"unknown placeholder\(s\) \{PR\}"):
            resolve_uri_placeholders("gs://b/{PR}/", env=GITHUB_PR)

    def test_option_name_in_the_error(self):
        """The error names the option it came from."""
        with pytest.raises(ConfigurationError, match="--some-uri"):
            resolve_uri_placeholders("gs://b/{pr}/", "--some-uri", env={})


class TestReject:
    """Options that don't fill placeholders in refuse them."""

    def test_rejects_pr_and_branch(self):
        """{pr} or {branch} in a state URI is an error naming the option."""
        with pytest.raises(ConfigurationError, match=r"--state-uri .*\{pr\}"):
            reject_uri_placeholders("gs://b/prs/{pr}/manifest.json", "--state-uri")
        with pytest.raises(ConfigurationError, match=r"\{branch\}"):
            reject_uri_placeholders("gs://b/{branch}/", "--state-uri")

    def test_accepts_plain_uris(self):
        """A URI without them, or none at all, passes."""
        reject_uri_placeholders("gs://b/dbt-state/manifest.json", "--state-uri")
        reject_uri_placeholders(None, "--state-uri")
