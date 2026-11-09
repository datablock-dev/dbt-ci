"""Tests for keeping finalize from publishing an older commit's manifest over a newer one."""

import os
import subprocess
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dbt_ci.commands.finalize.publish_order import (
    COMMIT_RECORD,
    Commit,
    published_is_newer,
    read_published_commit,
)
from dbt_ci.commands.finalize.upload import finalize_upload_files, upload_manifest

URI = "gs://bucket/dbt-state"
MANIFEST = {"nodes": {"model.demo.a": {}}}


def git(repo: Path, *args: str, when: int | None = None) -> str:
    """Run git in a repository, optionally with a fixed commit time, and return stdout."""
    env = None
    if when is not None:
        stamp = f"@{when} +0000"
        env = {**os.environ, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}
    result = subprocess.run(
        ["git", "-c", "user.email=ci@example.com", "-c", "user.name=ci", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout.strip()


def commit(repo: Path, name: str, when: int) -> str:
    """Add a commit at the given time and return its SHA."""
    (repo / f"{name}.txt").write_text(name)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", name, when=when)
    return git(repo, "rev-parse", "HEAD")


class FakeStorage:
    """An in-memory bucket offering the connector's upload, download and list."""

    def __init__(self):
        """Start with an empty bucket."""
        self.objects: dict[str, object] = {}

    def upload(self, uri: str, data: object, content_type: str) -> None:
        """Store an object."""
        self.objects[uri] = data

    def download(self, uri: str) -> object:
        """Return a stored object, failing like the real connectors when it is missing."""
        if uri not in self.objects:
            raise RuntimeError(f"Failed to download {uri}")
        return self.objects[uri]

    def list(self, prefix: str) -> list[str]:
        """Return the stored URIs starting with the prefix."""
        return [uri for uri in self.objects if uri.startswith(prefix)]

    def connector(self) -> dict:
        """Return a storage connector config backed by this bucket."""
        return {
            "name": "fake",
            "client": MagicMock(),
            "upload": self.upload,
            "download": self.download,
            "list": self.list,
        }

    def publish(self, sha: str | None, committed_at: int | None = None) -> None:
        """Pretend an earlier finalize published a manifest built from `sha`."""
        self.objects[f"{URI}/manifest.json"] = {"from": sha}
        self.objects[f"{URI}/{COMMIT_RECORD}"] = {"commit": sha, "committed_at": committed_at}


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> dict[str, str]:
    """A repo on main with commits a → b → c, and a side branch off a; HEAD is at c."""
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    shas = {"a": commit(path, "a", 1_000), "b": commit(path, "b", 2_000)}
    shas["c"] = commit(path, "c", 3_000)
    git(path, "checkout", "-qb", "side", shas["a"])
    shas["side_old"] = commit(path, "side_old", 1_500)
    shas["side_new"] = commit(path, "side_new", 9_000)
    git(path, "checkout", "-q", "main")
    monkeypatch.chdir(path)
    for name in ("GITHUB_SHA", "CI_COMMIT_SHA", "BUILDKITE_COMMIT", "CIRCLE_SHA1"):
        monkeypatch.delenv(name, raising=False)
    shas["path"] = str(path)
    return shas


def checkout(repo: dict[str, str], name: str) -> None:
    """Check out one of the fixture's commits."""
    git(Path(repo["path"]), "checkout", "-q", repo[name])


def finalize_manifest(storage: FakeStorage, force: bool = False) -> None:
    """Run upload_manifest for the checked-out commit against the fake bucket."""
    cache = MagicMock()
    cache.get_cache.return_value = MANIFEST
    upload_manifest(URI, cache, storage.upload, connector=storage.connector(), force=force)


class TestPublishedIsNewer:
    """Test how the published commit is compared with this run's."""

    def test_ancestry_decides(self, repo):
        """A descendant is newer and an ancestor older, whatever the commit times say."""
        old, new = Commit(repo["a"], 9_999), Commit(repo["c"], 1)
        assert published_is_newer(old, new) is True
        assert published_is_newer(new, old) is False

    def test_same_commit_is_not_newer(self, repo):
        """A re-run of the same commit replaces its own manifest."""
        assert published_is_newer(Commit(repo["c"]), Commit(repo["c"])) is False

    def test_diverged_commits_compare_times(self, repo):
        """Unrelated commits fall back to their commit times."""
        ours = Commit(repo["c"], 3_000)
        assert published_is_newer(ours, Commit(repo["side_new"], 9_000)) is True
        assert published_is_newer(ours, Commit(repo["side_old"], 1_500)) is False

    def test_unknown_commit_compares_times(self, repo):
        """A commit git cannot find or fetch is judged by the recorded time alone."""
        missing = "f" * 40
        ours = Commit(repo["c"], 3_000)
        assert published_is_newer(ours, Commit(missing, 4_000)) is True
        assert published_is_newer(ours, Commit(missing, 2_000)) is False
        assert published_is_newer(ours, Commit(missing, None)) is False
        assert published_is_newer(Commit(repo["c"], None), Commit(missing, 4_000)) is False

    def test_missing_commit_is_fetched_from_origin(self, repo, tmp_path, monkeypatch):
        """A clone made before the published commit existed fetches it to compare."""
        origin = Path(repo["path"])
        clone = tmp_path / "clone"
        subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)
        newer = commit(origin, "d", 500)  # an older time: only ancestry can tell
        monkeypatch.chdir(clone)
        assert published_is_newer(Commit(repo["c"], 3_000), Commit(newer, 500)) is True


class TestReadPublishedCommit:
    """Test reading the record finalize keeps next to manifest.json."""

    def test_no_record(self):
        """A bucket without a record (or a record without a commit) has no commit."""
        storage = FakeStorage()
        assert read_published_commit(URI, storage.connector()) is None
        storage.publish(None)
        assert read_published_commit(URI, storage.connector()) is None

    def test_record(self):
        """The commit and its time are read back."""
        storage = FakeStorage()
        storage.publish("a" * 40, 123)
        assert read_published_commit(URI, storage.connector()) == Commit("a" * 40, 123)

    def test_unreadable_record(self, caplog):
        """A record that can't be read is treated as missing, with a warning."""
        storage = FakeStorage()
        storage.publish("a" * 40)
        connector = {**storage.connector(), "download": MagicMock(side_effect=RuntimeError("x"))}
        assert read_published_commit(URI, connector) is None
        assert "commit is unknown" in caplog.text


class TestUploadManifestOrder:
    """Test that finalize only replaces manifest.json with a manifest at least as new."""

    def test_first_upload_records_the_commit(self, repo):
        """Without a record the manifest is published and the commit recorded."""
        storage = FakeStorage()
        finalize_manifest(storage)
        assert storage.objects[f"{URI}/manifest.json"] == MANIFEST
        assert storage.objects[f"{URI}/{repo['c']}/manifest.json"] == MANIFEST
        record = storage.objects[f"{URI}/{COMMIT_RECORD}"]
        assert record["commit"] == repo["c"]
        assert record["committed_at"] == 3_000

    def test_newer_commit_replaces_older(self, repo):
        """A deploy of a later commit replaces the published manifest."""
        storage = FakeStorage()
        storage.publish(repo["b"], 2_000)
        finalize_manifest(storage)
        assert storage.objects[f"{URI}/manifest.json"] == MANIFEST
        assert storage.objects[f"{URI}/{COMMIT_RECORD}"]["commit"] == repo["c"]

    def test_older_commit_keeps_newer(self, repo, caplog):
        """A late or re-run deploy of an older commit keeps the newer manifest."""
        checkout(repo, "a")
        storage = FakeStorage()
        storage.publish(repo["c"], 3_000)
        finalize_manifest(storage)
        assert storage.objects[f"{URI}/manifest.json"] == {"from": repo["c"]}
        assert storage.objects[f"{URI}/{COMMIT_RECORD}"]["commit"] == repo["c"]
        # Its own per-commit copy is still right, so it is kept
        assert storage.objects[f"{URI}/{repo['a']}/manifest.json"] == MANIFEST
        assert "Not replacing" in caplog.text and "--force-manifest" in caplog.text

    def test_force_replaces_newer(self, repo, caplog):
        """--force-manifest publishes the older manifest anyway, e.g. for a rollback."""
        checkout(repo, "a")
        storage = FakeStorage()
        storage.publish(repo["c"], 3_000)
        finalize_manifest(storage, force=True)
        assert storage.objects[f"{URI}/manifest.json"] == MANIFEST
        assert storage.objects[f"{URI}/{COMMIT_RECORD}"]["commit"] == repo["a"]
        assert "--force-manifest" in caplog.text

    def test_unknown_commit_uploads_as_before(self, repo, monkeypatch):
        """Without a commit for this run there is nothing to compare: it uploads."""
        storage = FakeStorage()
        storage.publish(repo["c"], 3_000)
        with patch("dbt_ci.commands.finalize.upload.current_commit_sha", return_value=None):
            finalize_manifest(storage)
        assert storage.objects[f"{URI}/manifest.json"] == MANIFEST
        assert storage.objects[f"{URI}/{COMMIT_RECORD}"]["commit"] is None

    def test_finalize_passes_the_connector_and_force(self, repo):
        """finalize_upload_files hands the connector and --force-manifest to the upload."""
        checkout(repo, "a")
        storage = FakeStorage()
        storage.publish(repo["c"], 3_000)
        args = Namespace(artifacts_uri=URI + "/", files=("manifest",), force_manifest=False)
        with (
            patch("dbt_ci.commands.finalize.upload.CacheManager") as cache,
            patch(
                "dbt_ci.commands.finalize.upload.init_storage_connector",
                return_value=(storage.connector(), URI),
            ),
        ):
            cache.return_value.get_cache.return_value = MANIFEST
            finalize_upload_files(args)
            assert storage.objects[f"{URI}/manifest.json"] == {"from": repo["c"]}
            finalize_upload_files(Namespace(**{**vars(args), "force_manifest": True}))
            assert storage.objects[f"{URI}/manifest.json"] == MANIFEST
