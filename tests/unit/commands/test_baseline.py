"""Unit tests for comparing against the manifest at the merge base (--baseline merge-base)."""

import json
import subprocess
from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest

from dbt_ci.commands.finalize.upload import current_commit_sha, upload_manifest
from dbt_ci.commands.init.baseline import (
    Baseline,
    archive_template,
    archived_shas,
    find_archived_manifest,
    prefix_of,
    resolve_baseline,
)
from dbt_ci.commands.init.state_modified import StateModified
from dbt_ci.commands.report.index import render_baseline
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
        "compare_to": "merge-base",
        "state_uri": None,
        "reference_state": None,
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


HEAD = "f" * 40


class TestResolveBaseline:
    """Test when the merge base is used, how its manifest is found, and the fallbacks."""

    @pytest.fixture(autouse=True)
    def head(self):
        """The branch has a commit of its own on top of the merge base."""
        with patch(f"{BASELINE}._head_sha", return_value=HEAD):
            yield

    def test_latest(self, tmp_path):
        """--compare-to latest never looks at git."""
        with patch(f"{BASELINE}.GitAdapter") as git:
            assert resolve_baseline(_args(tmp_path, compare_to="latest")) is None
        git.assert_not_called()

    def test_programmatic_callers_default_to_latest(self, tmp_path):
        """Only the CLI defaults to auto; args without compare_to keep the old behaviour."""
        args = _args(tmp_path)
        del args.compare_to
        with patch(f"{BASELINE}.GitAdapter") as git:
            assert resolve_baseline(args) is None
        git.assert_not_called()

    def test_kept_manifest_next_to_the_state(self, tmp_path):
        """The copy finalize kept next to the state is used and written for the comparison."""
        args = _args(tmp_path, state_uri="gs://bucket/dbt-state/manifest.json")
        with (
            patch(f"{BASELINE}.GitAdapter", return_value=_git()),
            patch(
                f"{BASELINE}.find_archived_manifest", return_value=(SHA[2], {"nodes": {}})
            ) as find,
        ):
            baseline = resolve_baseline(args)
        find.assert_called_once_with("gs://bucket/dbt-state/{sha}/manifest.json", SHA)
        assert baseline is not None
        assert (baseline.source, baseline.sha, baseline.commits_before_merge_base) == (
            "archived",
            SHA[2],
            2,
        )
        assert json.loads((tmp_path / ".dbtstate-baseline" / "manifest.json").read_text()) == {
            "nodes": {}
        }

    def test_compiles_when_nothing_is_kept(self, tmp_path):
        """Without a kept manifest the merge base is compiled."""
        args = _args(tmp_path, state_uri="gs://bucket/dbt-state/manifest.json")
        with (
            patch(f"{BASELINE}.GitAdapter", return_value=_git()),
            patch(f"{BASELINE}.find_archived_manifest", return_value=None),
            patch(f"{BASELINE}.compile_merge_base") as compile_merge_base,
        ):
            baseline = resolve_baseline(args)
        assert baseline is not None and baseline.source == "compiled"
        compile_merge_base.assert_called_once()

    @pytest.mark.parametrize("mode, level", [("auto", "INFO"), ("merge-base", "WARNING")])
    def test_no_commits_of_its_own(self, tmp_path, caplog, mode, level):
        """On the base branch itself (e.g. a deploy on main) the latest state is used."""
        with (
            caplog.at_level("INFO"),
            patch(f"{BASELINE}.GitAdapter", return_value=_git(merge_base=HEAD)),
            patch(f"{BASELINE}.compile_merge_base") as compile_merge_base,
        ):
            assert resolve_baseline(_args(tmp_path, compare_to=mode)) is None
        compile_merge_base.assert_not_called()
        record = next(r for r in caplog.records if "no commits of its own" in r.message)
        assert record.levelname == level

    @pytest.mark.parametrize(
        "overrides, git, compile_error, expected",
        [
            ({}, _git(merge_base=None), None, "Could not find where this branch started"),
            ({"runner": "docker"}, _git(), None, "not supported with the Docker runner"),
            ({}, _git(), RuntimeError("dbt parse failed"), "dbt parse failed"),
        ],
    )
    @pytest.mark.parametrize("mode, level", [("auto", "INFO"), ("merge-base", "WARNING")])
    def test_falls_back_to_latest(
        self, tmp_path, caplog, overrides, git, compile_error, expected, mode, level
    ):
        """Anything that prevents a baseline leaves today's behaviour, quietly in auto mode."""
        with (
            caplog.at_level("INFO"),
            patch(f"{BASELINE}.GitAdapter", return_value=git),
            patch(f"{BASELINE}.compile_merge_base", side_effect=compile_error),
        ):
            assert resolve_baseline(_args(tmp_path, compare_to=mode, **overrides)) is None
        record = next(r for r in caplog.records if expected in r.message)
        assert record.levelname == level
        assert "comparing against the latest state" in record.message

    def test_no_git_falls_back(self, tmp_path):
        """No repository at all is a fallback, not a failure."""
        with patch(f"{BASELINE}.GitAdapter", side_effect=subprocess.CalledProcessError(128, "git")):
            assert resolve_baseline(_args(tmp_path, compare_to="auto")) is None


class TestArchiveTemplate:
    """Test where kept manifests are looked for, derived from the state."""

    @pytest.mark.parametrize(
        "args, expected",
        [
            (
                {"state_uri": "gs://b/dbt-state/manifest.json"},
                "gs://b/dbt-state/{sha}/manifest.json",
            ),
            ({"state_uri": "s3://b/dbt-state/"}, "s3://b/dbt-state/{sha}/manifest.json"),
            ({"reference_state": "state"}, "state/{sha}/manifest.json"),
            ({"reference_state": "state/manifest.json"}, "state/{sha}/manifest.json"),
            ({}, None),
        ],
    )
    def test_next_to_the_state(self, args, expected):
        """Copies sit in a folder per commit next to the state's manifest."""
        assert archive_template(Namespace(**args)) == expected


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


class TestFinalizeKeepsACopyPerCommit:
    """Test that finalize keeps the manifest per commit next to the latest one."""

    def test_copy_next_to_the_latest(self):
        """The manifest goes to <uri>/manifest.json and <uri>/<commit>/manifest.json."""
        cache = MagicMock()
        cache.get_cache.return_value = {"nodes": {}}
        storage = MagicMock()
        with patch("dbt_ci.commands.finalize.upload.current_commit_sha", return_value=SHA[0]):
            upload_manifest("gs://b/dbt-state", cache, storage)
        assert [c.args[0] for c in storage.call_args_list] == [
            "gs://b/dbt-state/manifest.json",
            f"gs://b/dbt-state/{SHA[0]}/manifest.json",
        ]

    def test_no_commit_no_copy(self):
        """Without a known commit only the latest manifest is uploaded."""
        cache = MagicMock()
        cache.get_cache.return_value = {"nodes": {}}
        storage = MagicMock()
        with patch("dbt_ci.commands.finalize.upload.current_commit_sha", return_value=None):
            upload_manifest("gs://b/dbt-state", cache, storage)
        assert storage.call_count == 1

    def test_commit_from_git_or_ci_environment(self, monkeypatch):
        """git is asked first; without a checkout the CI system's variable is used."""
        done = subprocess.CompletedProcess([], 0, stdout=SHA[0] + "\n", stderr="")
        with patch("dbt_ci.commands.finalize.upload.subprocess.run", return_value=done):
            assert current_commit_sha() == SHA[0]
        failed = subprocess.CompletedProcess([], 128, stdout="", stderr="not a repo")
        monkeypatch.setenv("GITHUB_SHA", SHA[1])
        with patch("dbt_ci.commands.finalize.upload.subprocess.run", return_value=failed):
            assert current_commit_sha() == SHA[1]
