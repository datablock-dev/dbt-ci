"""Unit tests for comparing against the manifest at the merge base (--baseline merge-base)."""

import json
import subprocess
from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest

from dbt_ci.commands.finalize.upload import fill_commit_sha
from dbt_ci.commands.init.baseline import (
    Baseline,
    archived_shas,
    find_archived_manifest,
    prefix_of,
    resolve_baseline,
)
from dbt_ci.commands.init.state_modified import StateModified
from dbt_ci.commands.report.index import render_baseline
from dbt_ci.errors import ConfigurationError
from dbt_ci.runners import resolve_dbt_commands

BASELINE = "dbt_ci.commands.init.baseline"
# Base-branch history from the merge base backwards, newest first
SHA = ["a" * 40, "b" * 40, "c" * 40]
TEMPLATE = "gs://bucket/dbt-state/{sha}/manifest.json"


def _connector(listed: list[str] | Exception, downloads: dict[str, dict]) -> MagicMock:
    """A storage connector that lists the given URIs and serves the given downloads."""
    connector = {
        "list": MagicMock(side_effect=listed if isinstance(listed, Exception) else None),
        "download": MagicMock(side_effect=lambda uri: downloads[uri]),
    }
    if not isinstance(listed, Exception):
        connector["list"].return_value = listed
    return connector


def _find(listed, downloads):
    """Run find_archived_manifest against a mocked GCS connector."""
    connector = _connector(listed, downloads)
    with patch(f"{BASELINE}.init_storage_connector", return_value=(connector, TEMPLATE)):
        return find_archived_manifest(TEMPLATE, SHA), connector


class TestFindArchivedManifest:
    """Test the lookup of a manifest archived per commit."""

    def test_newest_archived_commit_wins(self):
        """With batched deploys the nearest archived commit before the merge base is used."""
        listed = [TEMPLATE.format(sha=SHA[2]), TEMPLATE.format(sha=SHA[1]), "gs://bucket/other"]
        downloads = {TEMPLATE.format(sha=SHA[1]): {"from": "b"}}
        (sha, manifest), connector = _find(listed, downloads)
        assert (sha, manifest) == (SHA[1], {"from": "b"})
        connector["list"].assert_called_once_with("gs://bucket/dbt-state/")
        connector["download"].assert_called_once()

    def test_nothing_archived(self):
        """No archived commit in the history means no archived baseline."""
        found, connector = _find([TEMPLATE.format(sha="d" * 40)], {})
        assert found is None
        connector["download"].assert_not_called()

    def test_listing_not_allowed_tries_each_commit(self):
        """Without permission to list, each commit is tried in turn."""
        downloads = {TEMPLATE.format(sha=SHA[2]): {"from": "c"}}
        found, connector = _find(RuntimeError("403"), downloads)
        assert found == (SHA[2], {"from": "c"})
        assert connector["download"].call_count == 3

    def test_local_path(self, tmp_path):
        """A local template is checked file by file, and a directory means its manifest."""
        (tmp_path / SHA[1]).mkdir()
        (tmp_path / SHA[1] / "manifest.json").write_text('{"from": "b"}')
        template = str(tmp_path / "{sha}")
        assert find_archived_manifest(template, SHA) == (SHA[1], {"from": "b"})

    def test_template_needs_the_placeholder(self):
        """A URI without {sha} cannot describe one manifest per commit."""
        with pytest.raises(ValueError, match="sha"):
            find_archived_manifest("gs://bucket/manifest.json", SHA)

    def test_prefix_and_sha_matching(self):
        """Only full SHAs in the {sha} position of the template count."""
        assert prefix_of(TEMPLATE) == "gs://bucket/dbt-state/"
        uris = [
            TEMPLATE.format(sha=SHA[0]),
            TEMPLATE.format(sha="abc"),
            f"gs://bucket/dbt-state/{SHA[1]}/cache.json",
        ]
        assert archived_shas(TEMPLATE, uris) == {SHA[0]}


def _args(tmp_path, **overrides) -> Namespace:
    """Build init args for resolving a baseline."""
    defaults = {
        "baseline": "merge-base",
        "baseline_uri": None,
        "baseline_lookback": 50,
        "dbt_project_dir": str(tmp_path),
        "runner": "local",
    }
    return Namespace(**{**defaults, **overrides})


def _git(merge_base: str | None = SHA[0]) -> MagicMock:
    """A git adapter that found the given merge base."""
    git = MagicMock()
    git.merge_base_found = merge_base is not None
    git.merge_base_sha.return_value = merge_base
    git.first_parent_history.return_value = SHA
    return git


class TestResolveBaseline:
    """Test the order in which a baseline is found, and the fallbacks."""

    def test_latest_is_the_default(self, tmp_path):
        """Without --baseline merge-base nothing changes."""
        assert resolve_baseline(_args(tmp_path, baseline="latest")) is None

    def test_archived_manifest(self, tmp_path):
        """An archived manifest is written where the comparison reads it."""
        with (
            patch(f"{BASELINE}.GitAdapter", return_value=_git()),
            patch(f"{BASELINE}.find_archived_manifest", return_value=(SHA[2], {"nodes": {}})),
        ):
            baseline = resolve_baseline(_args(tmp_path, baseline_uri=TEMPLATE))
        assert baseline is not None
        assert (baseline.source, baseline.sha, baseline.commits_before_merge_base) == (
            "archived",
            SHA[2],
            2,
        )
        assert json.loads((tmp_path / ".dbtstate-baseline" / "manifest.json").read_text()) == {
            "nodes": {}
        }

    def test_compiles_when_nothing_is_archived(self, tmp_path):
        """Without an archived manifest the merge base is compiled."""
        with (
            patch(f"{BASELINE}.GitAdapter", return_value=_git()),
            patch(f"{BASELINE}.find_archived_manifest", return_value=None),
            patch(f"{BASELINE}.compile_merge_base") as compile_merge_base,
        ):
            baseline = resolve_baseline(_args(tmp_path, baseline_uri=TEMPLATE))
        assert baseline is not None and baseline.source == "compiled"
        compile_merge_base.assert_called_once()

    @pytest.mark.parametrize(
        "overrides, git, compile_error, expected",
        [
            ({}, _git(merge_base=None), None, "could not find where this branch started"),
            ({"runner": "docker"}, _git(), None, "not supported with the Docker runner"),
            ({}, _git(), RuntimeError("dbt parse failed"), "dbt parse failed"),
        ],
    )
    def test_falls_back_to_latest_with_a_warning(
        self, tmp_path, caplog, overrides, git, compile_error, expected
    ):
        """Anything that prevents a baseline leaves today's behaviour, and says why."""
        with (
            caplog.at_level("WARNING"),
            patch(f"{BASELINE}.GitAdapter", return_value=git),
            patch(f"{BASELINE}.compile_merge_base", side_effect=compile_error),
        ):
            assert resolve_baseline(_args(tmp_path, **overrides)) is None
        assert expected in caplog.text
        assert "comparing against the latest state instead" in caplog.text

    def test_no_git_falls_back(self, tmp_path, caplog):
        """No repository at all is a fallback, not a failure."""
        with (
            caplog.at_level("WARNING"),
            patch(f"{BASELINE}.GitAdapter", side_effect=subprocess.CalledProcessError(128, "git")),
        ):
            assert resolve_baseline(_args(tmp_path)) is None


class TestDescribe:
    """Test the line the log and the report show."""

    def test_descriptions(self):
        """Each source is described in plain words."""
        assert Baseline("d", SHA[0], "compiled", SHA[0]).describe() == (
            f"the merge base {SHA[0][:12]}, compiled for this run"
        )
        assert Baseline("d", SHA[0], "archived", SHA[0]).describe() == (
            f"the manifest archived for the merge base {SHA[0][:12]}"
        )
        assert "2 commit(s) before the merge base" in (
            Baseline("d", SHA[2], "archived", SHA[0], 2).describe()
        )

    def test_report_line(self):
        """The report names the baseline, and says nothing without one."""
        cache = {"config": {"baseline": Baseline("d", SHA[0], "compiled", SHA[0]).to_dict()}}
        assert render_baseline(cache)[0].startswith("Compared against the merge base")
        assert render_baseline({"config": {}}) == []


class TestComparisonState:
    """Test that only the comparison uses the baseline; defer keeps the latest state."""

    def test_state_flag_points_at_the_baseline(self):
        """dbt gets --state for the baseline in place of the reference state."""
        args = Namespace(
            runner="local", reference_state="/repo/state", comparison_state="/repo/baseline"
        )
        commands = resolve_dbt_commands(["ls"], args)
        assert commands[commands.index("--state") + 1] == "/repo/baseline"
        assert commands.count("--state") == 1

    def test_docker_maps_the_baseline_through_the_volumes(self):
        """The Docker runner sees the baseline at its container path, even with DBT_STATE set."""
        args = Namespace(
            runner="docker",
            reference_state="/repo/state",
            comparison_state="/repo/dbt/.dbtstate-baseline",
            docker_volumes=["/repo/dbt:/dbt"],
            docker_env=["DBT_STATE=/dbt/.dbtstate"],
        )
        commands = resolve_dbt_commands(["ls"], args)
        assert commands[commands.index("--state") + 1] == "/dbt/.dbtstate-baseline"

    def test_state_modified_compares_against_the_baseline(self):
        """The comparison args swap the state; the args other commands see are untouched."""
        args = Namespace(comparison_strategy="dbt", reference_state="/repo/state")
        state = StateModified(args)
        state.comparison_state = "/repo/baseline"
        comparison = state._comparison_args()
        assert comparison.reference_state == "/repo/baseline"
        assert args.reference_state == "/repo/state"
        assert not hasattr(args, "comparison_state")


class TestFillCommitSha:
    """Test the {sha} placeholder in finalize's artifacts URI."""

    def test_no_placeholder(self):
        """A URI without {sha} is used as given."""
        assert fill_commit_sha("gs://b/latest/") == "gs://b/latest/"

    def test_from_git(self):
        """The checked-out commit fills {sha}."""
        done = subprocess.CompletedProcess([], 0, stdout=SHA[0] + "\n", stderr="")
        with patch("dbt_ci.commands.finalize.upload.subprocess.run", return_value=done):
            assert fill_commit_sha("gs://b/{sha}/") == f"gs://b/{SHA[0]}/"

    def test_from_ci_environment(self, monkeypatch):
        """Without git, the CI system's commit variable is used."""
        failed = subprocess.CompletedProcess([], 128, stdout="", stderr="not a repo")
        monkeypatch.setenv("GITHUB_SHA", SHA[1])
        with patch("dbt_ci.commands.finalize.upload.subprocess.run", return_value=failed):
            assert fill_commit_sha("gs://b/{sha}/") == f"gs://b/{SHA[1]}/"

    def test_unknown_commit_is_an_error(self, monkeypatch):
        """Archiving under an unknown commit would make the manifest unfindable."""
        failed = subprocess.CompletedProcess([], 128, stdout="", stderr="not a repo")
        for name in ("GITHUB_SHA", "CI_COMMIT_SHA", "BUILDKITE_COMMIT", "CIRCLE_SHA1"):
            monkeypatch.delenv(name, raising=False)
        with patch("dbt_ci.commands.finalize.upload.subprocess.run", return_value=failed):
            with pytest.raises(ConfigurationError, match="sha"):
                fill_commit_sha("gs://b/{sha}/")
