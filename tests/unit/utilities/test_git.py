"""Unit tests for the git adapter used during state comparison."""

import os
import subprocess
from argparse import Namespace
from unittest.mock import patch

import pytest

from dbt_ci.utilities.git import GitAdapter


def _make_adapter(changes: list[list[str]], dbt_project_dir: str = "dbt") -> GitAdapter:
    """Build a GitAdapter with its git calls bypassed and a fixed set of diff rows."""
    adapter = GitAdapter.__new__(GitAdapter)
    adapter.args = Namespace(dbt_project_dir=dbt_project_dir)
    adapter.base_branch = "main"
    adapter.changes = changes
    # Resolve the project directory against the working directory without calling git
    adapter.repo_root = os.getcwd()
    return adapter


class TestClassifyChanges:
    """Test that raw `git diff --name-status` rows map to change types."""

    def test_plain_statuses(self):
        """M/A/D map to modified/added/deleted."""
        adapter = _make_adapter(
            [
                ["M", "dbt/models/a.sql"],
                ["A", "dbt/models/b.sql"],
                ["D", "dbt/models/c.sql"],
            ]
        )
        assert adapter.get_changed_files() == {
            "modified": ["models/a.sql"],
            "added": ["models/b.sql"],
            "deleted": ["models/c.sql"],
        }

    def test_rename_becomes_delete_plus_add(self):
        """R100 carries a similarity score and must expand into a delete and an add."""
        adapter = _make_adapter([["R100", "dbt/models/old.sql", "dbt/models/new.sql"]])

        result = adapter.get_changed_files()

        assert result["deleted"] == ["models/old.sql"]
        assert result["added"] == ["models/new.sql"]

    def test_copy_becomes_add(self):
        """C085 records a new file at the destination path only."""
        adapter = _make_adapter([["C085", "dbt/models/src.sql", "dbt/models/copy.sql"]])

        result = adapter.get_changed_files()

        assert result["added"] == ["models/copy.sql"]
        assert "deleted" not in result

    def test_modified_status_with_score_is_still_modified(self):
        """A status code carrying a score is matched on its first character."""
        adapter = _make_adapter([["M100", "dbt/models/a.sql"]])
        assert adapter.get_changed_files() == {"modified": ["models/a.sql"]}

    def test_unknown_status_is_skipped(self):
        """Statuses dbt-ci doesn't model (e.g. unmerged) are ignored, not crashed on."""
        adapter = _make_adapter(
            [
                ["U", "dbt/models/conflict.sql"],
                ["M", "dbt/models/a.sql"],
            ]
        )
        assert adapter.get_changed_files() == {"modified": ["models/a.sql"]}

    def test_files_outside_project_dir_are_ignored(self):
        """Changes outside the dbt project directory are not dbt changes."""
        adapter = _make_adapter(
            [
                ["M", "README.md"],
                ["M", "dbt/models/a.sql"],
            ]
        )
        assert adapter.get_changed_files() == {"modified": ["models/a.sql"]}

    def test_extension_filter(self):
        """Only files matching the requested extensions are returned."""
        adapter = _make_adapter(
            [
                ["M", "dbt/models/a.sql"],
                ["M", "dbt/models/schema.yml"],
            ]
        )
        assert adapter.get_changed_files(extensions=[".sql"]) == {"modified": ["models/a.sql"]}


class TestDiffAgainstBase:
    """Test the diff range used to compute the change set."""

    def test_prefers_three_dot_diff(self):
        """The merge-base (three-dot) diff is what isolates this branch's own changes."""
        adapter = GitAdapter.__new__(GitAdapter)
        adapter.base_branch = "main"

        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="M\tdbt/models/a.sql\n", stderr=""
        )
        with patch("dbt_ci.utilities.git.subprocess.run", return_value=completed) as mock_run:
            changes = adapter._diff_against_base()

        assert changes == [["M", "dbt/models/a.sql"]]
        assert mock_run.call_args_list[0][0][0] == [
            "git",
            "diff",
            "--name-status",
            "origin/main...HEAD",
        ]

    def test_raises_when_both_diffs_fail(self):
        """A completely unusable base ref is an error rather than an empty change set."""
        adapter = GitAdapter.__new__(GitAdapter)
        adapter.base_branch = "main"

        failure = subprocess.CompletedProcess(
            args=[], returncode=128, stdout="", stderr="bad revision"
        )
        with patch("dbt_ci.utilities.git.subprocess.run", return_value=failure):
            with pytest.raises(RuntimeError, match="Could not diff against 'origin/main'"):
                adapter._diff_against_base()


class FakeGit:
    """Answer git commands the way a clone missing its merge base would."""

    def __init__(self, shallow: bool, found_after: int | None, fetch_fails: bool = False):
        """found_after: how many deepening fetches it takes for the merge base to appear."""
        self.shallow = shallow
        self.found_after = found_after
        self.fetch_fails = fetch_fails
        self.fetches = 0
        self.commands: list[list[str]] = []

    def has_merge_base(self) -> bool:
        """Report whether the merge base is present yet."""
        return self.found_after is not None and self.fetches >= self.found_after

    def __call__(self, command, **_kwargs):
        """Return what git would for one command."""
        self.commands.append(command)

        def done(code=0, stdout=""):
            return subprocess.CompletedProcess(command, code, stdout=stdout, stderr="")

        if command == ["git", "rev-parse", "HEAD"]:
            return done(stdout="abc123\n")
        if command[:2] == ["git", "rev-parse"]:
            return done(stdout="true\n" if self.shallow else "false\n")
        if command[:2] == ["git", "fetch"]:
            self.fetches += 1
            return done(128 if self.fetch_fails else 0)
        if command[:2] == ["git", "merge-base"]:
            return done(0 if self.has_merge_base() else 1)
        if command[-1] == "origin/main...HEAD":
            return done(0, "A\tdbt/models/mine.sql\n") if self.has_merge_base() else done(128)
        # Two-dot diff: also reports a change merged into main since the branch point
        return done(0, "A\tdbt/models/mine.sql\nD\tdbt/models/theirs.sql\n")


def _diff(fake: FakeGit, caplog=None):
    """Run _diff_against_base against a fake git."""
    adapter = GitAdapter.__new__(GitAdapter)
    adapter.base_branch = "main"
    with patch("dbt_ci.utilities.git.subprocess.run", side_effect=fake):
        return adapter._diff_against_base()


class TestMissingMergeBase:
    """Test what happens when the merge base is not in the clone."""

    def test_shallow_clone_is_deepened(self, caplog):
        """A shallow clone fetches more history and then uses the merge-base diff."""
        fake = FakeGit(shallow=True, found_after=2)
        assert _diff(fake) == [["A", "dbt/models/mine.sql"]]
        fetches = [c for c in fake.commands if c[:2] == ["git", "fetch"]]
        assert [c[2] for c in fetches] == ["--deepen=50", "--deepen=200"]
        # HEAD's own history is asked for too, not only the base branch's
        assert fetches[0][3:] == ["origin", "main", "abc123"]
        assert "Could not find where this branch started" not in caplog.text

    def test_warns_when_history_runs_out(self, caplog):
        """If deepening never finds it, the direct diff is used with a visible warning."""
        fake = FakeGit(shallow=True, found_after=None)
        with caplog.at_level("WARNING"):
            changes = _diff(fake)
        assert ["D", "dbt/models/theirs.sql"] in changes
        assert len([c for c in fake.commands if c[:2] == ["git", "fetch"]]) == 3
        assert "may be counted as this branch's own" in caplog.text
        assert "fetch-depth: 0" in caplog.text

    def test_full_clone_is_not_deepened(self, caplog):
        """Unrelated histories in a full clone warn without trying to fetch."""
        fake = FakeGit(shallow=False, found_after=None)
        with caplog.at_level("WARNING"):
            _diff(fake)
        assert not [c for c in fake.commands if c[:2] == ["git", "fetch"]]
        assert "share no history" in caplog.text

    def test_failed_fetch_stops_deepening(self, caplog):
        """A fetch that fails (e.g. no network) is retried without HEAD, then stops."""
        fake = FakeGit(shallow=True, found_after=1, fetch_fails=True)
        with caplog.at_level("WARNING"):
            _diff(fake)
        fetches = [c for c in fake.commands if c[:2] == ["git", "fetch"]]
        assert [c[3:] for c in fetches] == [["origin", "main", "abc123"], ["origin", "main"]]
        assert "fetch-depth: 0" in caplog.text


def _git(cwd, *args):
    """Run a git command in a directory with a fixed identity, failing on error."""
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


class TestShallowCloneEndToEnd:
    """Test deepening against real git repositories."""

    def test_merge_commit_checkout_at_depth_one(self, tmp_path, monkeypatch, caplog):
        """A depth-1 PR merge checkout finds only its own files after main moved on.

        Without the merge base, the direct diff would also report 'later', merged into
        main after the PR's merge commit was made, as deleted by this branch.
        """
        origin = tmp_path / "origin"
        origin.mkdir()
        _git(origin, "init", "-q", "-b", "main")
        for name in ("a", "b"):
            (origin / name).write_text(name)
            _git(origin, "add", ".")
            _git(origin, "commit", "-qm", name)
        _git(origin, "checkout", "-qb", "feature")
        (origin / "mine").write_text("mine")
        _git(origin, "add", ".")
        _git(origin, "commit", "-qm", "mine")
        _git(origin, "checkout", "-q", "main")
        (origin / "theirs").write_text("theirs")
        _git(origin, "add", ".")
        _git(origin, "commit", "-qm", "theirs")
        _git(origin, "checkout", "-qb", "pr-merge")
        _git(origin, "merge", "-q", "--no-ff", "feature", "-m", "merge")
        # Someone merges into main after the PR's merge commit was created
        _git(origin, "checkout", "-q", "main")
        (origin / "later").write_text("later")
        _git(origin, "add", ".")
        _git(origin, "commit", "-qm", "later")

        clone = tmp_path / "clone"
        clone.mkdir()
        _git(clone, "init", "-q")
        _git(clone, "remote", "add", "origin", f"file://{origin}")
        _git(clone, "fetch", "-q", "--depth=1", "origin", "pr-merge")
        _git(clone, "checkout", "-q", "FETCH_HEAD")
        _git(clone, "fetch", "-q", "origin", "main")
        monkeypatch.chdir(clone)

        adapter = GitAdapter.__new__(GitAdapter)
        adapter.base_branch = "main"
        with caplog.at_level("DEBUG", logger="dbt_ci.utilities.git"):
            changes = adapter._diff_against_base()
        # On failure, show what git said, since this depends on the installed git version
        assert changes == [["A", "mine"]], caplog.text


class TestProjectDirMatching:
    """Test that changed paths are matched to the dbt project directory by path, not substring."""

    CHANGES = [
        ["M", "dbt/models/a.sql"],
        ["M", "analytics_dbt/models/b.sql"],
        ["M", "docs/dbt/c.sql"],
        ["M", "README.md"],
    ]

    @pytest.mark.parametrize("project_dir", ["dbt", "./dbt", "dbt/", "dbt/./"])
    def test_spellings_of_the_same_directory(self, project_dir, tmp_path, monkeypatch):
        """Relative spellings of the project directory all match the same files."""
        monkeypatch.chdir(tmp_path)
        adapter = _make_adapter(self.CHANGES, dbt_project_dir=project_dir)
        adapter.repo_root = str(tmp_path)
        assert adapter.get_changed_files() == {"modified": ["models/a.sql"]}

    def test_absolute_project_dir(self, tmp_path, monkeypatch):
        """An absolute project directory inside the repository is matched too."""
        monkeypatch.chdir(tmp_path)
        adapter = _make_adapter(self.CHANGES, dbt_project_dir=str(tmp_path / "dbt"))
        adapter.repo_root = str(tmp_path)
        assert adapter.get_changed_files() == {"modified": ["models/a.sql"]}

    def test_project_at_repository_root(self, tmp_path, monkeypatch):
        """A project at the repository root keeps every path unchanged."""
        monkeypatch.chdir(tmp_path)
        adapter = _make_adapter([["M", "models/a.sql"]], dbt_project_dir=".")
        adapter.repo_root = str(tmp_path)
        assert adapter.get_changed_files() == {"modified": ["models/a.sql"]}

    def test_run_from_a_subdirectory(self, tmp_path, monkeypatch):
        """The project directory is resolved from the working directory, not the repository root."""
        (tmp_path / "ci").mkdir()
        monkeypatch.chdir(tmp_path / "ci")
        adapter = _make_adapter(self.CHANGES, dbt_project_dir="../dbt")
        adapter.repo_root = str(tmp_path)
        assert adapter.get_changed_files() == {"modified": ["models/a.sql"]}

    def test_symlinked_working_directory(self, tmp_path, monkeypatch):
        """A working directory reached through a symlink still matches git's resolved root."""
        real = tmp_path / "real"
        (real / "dbt").mkdir(parents=True)
        link = tmp_path / "link"
        link.symlink_to(real)
        monkeypatch.chdir(link)
        adapter = _make_adapter(self.CHANGES, dbt_project_dir="dbt")
        adapter.repo_root = str(real)
        assert adapter.get_changed_files() == {"modified": ["models/a.sql"]}


class TestBestEffort:
    """Test the mode used when git is optional (explaining dbt-strategy changes)."""

    def test_fetches_never_prompt_and_missing_merge_base_is_not_warned(self, caplog):
        """No credential prompt on fetch, and no warning, since the diff is not relied on."""
        fake = FakeGit(shallow=True, found_after=None)
        adapter = GitAdapter.__new__(GitAdapter)
        adapter.base_branch = "main"
        adapter.best_effort = True
        envs = []

        def recording(command, **kwargs):
            """Record the environment each fetch runs with."""
            if command[:2] == ["git", "fetch"]:
                envs.append(kwargs.get("env"))
            return fake(command, **kwargs)

        with caplog.at_level("WARNING"):
            with patch("dbt_ci.utilities.git.subprocess.run", side_effect=recording):
                adapter._diff_against_base()

        assert envs and all(env["GIT_TERMINAL_PROMPT"] == "0" for env in envs)
        assert "Could not find where this branch started" not in caplog.text
        assert not getattr(adapter, "merge_base_found", False)


class TestReadBaseFile:
    """Test reading a project file as it was at the merge base."""

    def test_reads_at_the_merge_base_with_the_project_prefix(self):
        """The project-relative path is prefixed and read at the merge base commit."""
        adapter = _make_adapter([])
        calls = []

        def fake_run(command, **_kwargs):
            """Answer merge-base with a sha and show with file contents."""
            calls.append(command)
            stdout = "abc123\n" if command[1] == "merge-base" else "name: demo\n"
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

        with patch("dbt_ci.utilities.git.subprocess.run", side_effect=fake_run):
            assert adapter.read_base_file("dbt_project.yml") == "name: demo\n"
        assert calls[-1] == ["git", "show", "abc123:dbt/dbt_project.yml"]

    def test_no_merge_base(self):
        """Without a merge base there is nothing to read."""
        adapter = _make_adapter([])
        failed = subprocess.CompletedProcess([], 1, stdout="", stderr="no merge base")
        with patch("dbt_ci.utilities.git.subprocess.run", return_value=failed):
            assert adapter.read_base_file("dbt_project.yml") is None


def _out(cwd, *args) -> str:
    """Run a git command and return its output."""
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """
    A clone on a feature branch, with an origin whose main has a merged side branch.

    main: base -> side (merged with a merge commit) -> after; the feature branch starts
    at `after` and changes dbt/models/a.sql. Returns (clone, {name: sha}).
    """
    origin_work = tmp_path / "work"
    (origin_work / "dbt" / "models").mkdir(parents=True)
    _git(origin_work, "init", "-q", "-b", "main")
    (origin_work / "dbt" / "models" / "a.sql").write_text("select 1\n")
    (origin_work / "dbt" / "dbt_project.yml").write_text("name: demo\n")
    _git(origin_work, "add", "-A")
    _git(origin_work, "commit", "-qm", "base")
    shas = {"base": _out(origin_work, "rev-parse", "HEAD")}
    _git(origin_work, "checkout", "-qb", "side")
    (origin_work / "side.txt").write_text("side\n")
    _git(origin_work, "add", "-A")
    _git(origin_work, "commit", "-qm", "side")
    shas["side"] = _out(origin_work, "rev-parse", "HEAD")
    _git(origin_work, "checkout", "-q", "main")
    _git(origin_work, "merge", "-q", "--no-ff", "side", "-m", "merge side")
    shas["merge"] = _out(origin_work, "rev-parse", "HEAD")
    (origin_work / "after.txt").write_text("after\n")
    _git(origin_work, "add", "-A")
    _git(origin_work, "commit", "-qm", "after")
    shas["after"] = _out(origin_work, "rev-parse", "HEAD")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(origin_work), str(origin)], check=True)

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)
    _git(clone, "checkout", "-qb", "feature")
    (clone / "dbt" / "models" / "a.sql").write_text("select 2\n")
    _git(clone, "commit", "-qam", "change a")
    monkeypatch.chdir(clone)
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    return clone, shas


class TestAgainstARealRepository:
    """Test the adapter end to end on real git history."""

    def test_constructor_diffs_the_branch_against_its_merge_base(self, repo):
        """Constructing fetches the base, diffs from the merge base and records it."""
        _, shas = repo
        adapter = GitAdapter(Namespace(dbt_project_dir="dbt", base_ref="main"))
        assert adapter.merge_base_found
        assert adapter.merge_base_sha() == shas["after"]
        assert adapter.get_changed_files() == {"modified": ["models/a.sql"]}

    def test_first_parent_history(self, repo):
        """Following first parents skips the side branch's own commit."""
        adapter = GitAdapter(Namespace(dbt_project_dir="dbt", base_ref="main"))
        _, shas = repo
        history = adapter.first_parent_history(shas["after"], 10)
        assert history == [shas["after"], shas["merge"], shas["base"]]
        assert adapter.first_parent_history(shas["after"], 2) == [shas["after"], shas["merge"]]
        assert adapter.first_parent_history("0" * 40, 10) == []

    def test_read_base_file(self, repo):
        """A project file is read as it was at the merge base."""
        clone, _ = repo
        (clone / "dbt" / "dbt_project.yml").write_text("name: changed\n")
        adapter = GitAdapter(Namespace(dbt_project_dir="dbt", base_ref="main"))
        assert adapter.read_base_file("dbt_project.yml") == "name: demo\n"
        assert adapter.read_base_file("missing.yml") is None

    def test_base_branch_from_origin_head(self, repo):
        """Without --base-ref, origin's default branch is used."""
        assert GitAdapter(Namespace(dbt_project_dir="dbt")).base_branch == "main"

    def test_base_branch_from_github(self, repo, monkeypatch):
        """GITHUB_BASE_REF, set on pull_request events, comes before git's own guess."""
        monkeypatch.setenv("GITHUB_BASE_REF", " main \n")
        assert GitAdapter(Namespace(dbt_project_dir="dbt")).base_branch == "main"


def _resolver(responses: dict[tuple[str, ...], int]):
    """A fake git answering commands by their arguments, failing anything unlisted."""

    def run(command, **_kwargs):
        code = responses.get(tuple(command[1:]), 1)
        stdout = "origin/develop\n" if command[1] == "symbolic-ref" and code == 0 else ""
        return subprocess.CompletedProcess(command, code, stdout=stdout, stderr="")

    return run


class TestResolveBaseBranch:
    """Test the order in which the base branch is worked out."""

    def _resolve(self, responses, monkeypatch, **args):
        monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
        adapter = GitAdapter.__new__(GitAdapter)
        adapter.args = Namespace(**args)
        with patch("dbt_ci.utilities.git.subprocess.run", side_effect=_resolver(responses)):
            return adapter._resolve_base_branch()

    def test_explicit_base_ref_wins(self, monkeypatch):
        """--base-ref is used as given, without asking git."""
        assert self._resolve({}, monkeypatch, base_ref="release") == "release"

    def test_origin_head_after_auto_detection(self, monkeypatch):
        """If origin/HEAD isn't set yet, git is asked to detect it and asked again."""
        calls = iter([1, 0])

        def run(command, **_kwargs):
            if command[1] == "symbolic-ref":
                code = next(calls)
                return subprocess.CompletedProcess(
                    command, code, stdout="origin/develop\n" if code == 0 else "", stderr=""
                )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        adapter = GitAdapter.__new__(GitAdapter)
        adapter.args = Namespace()
        monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
        with patch("dbt_ci.utilities.git.subprocess.run", side_effect=run):
            assert adapter._resolve_base_branch() == "develop"

    def test_probes_master_when_main_is_missing(self, monkeypatch):
        """Without origin/HEAD, origin/main and then origin/master are tried."""
        responses = {("rev-parse", "--verify", "origin/master"): 0}
        assert self._resolve(responses, monkeypatch) == "master"

    def test_nothing_found(self, monkeypatch):
        """With no way to tell, the error says how to fix it."""
        with pytest.raises(RuntimeError, match="--base-ref"):
            self._resolve({}, monkeypatch)


class TestChangedFilesEdgeCases:
    """Test project-directory and extension handling in get_changed_files."""

    def test_requires_a_project_dir(self):
        """Without --dbt-project-dir changed files cannot be mapped."""
        adapter = _make_adapter([["M", "dbt/models/a.sql"]])
        adapter.args = Namespace(dbt_project_dir=None)
        with pytest.raises(ValueError, match="project directory"):
            adapter.get_changed_files()

    def test_remove_extensions(self):
        """remove_extensions drops file extensions from every path."""
        adapter = _make_adapter([["M", "dbt/models/a.sql"], ["A", "dbt/models/b.yml"]])
        assert adapter.get_changed_files(remove_extensions=True) == {
            "modified": ["models/a"],
            "added": ["models/b"],
        }

    def test_project_outside_the_repository(self, tmp_path, caplog):
        """A project outside the repository matches nothing and says why."""
        adapter = _make_adapter([["M", "dbt/models/a.sql"]], dbt_project_dir=str(tmp_path))
        adapter.repo_root = str(tmp_path / "repo")
        with caplog.at_level("WARNING"):
            assert adapter.get_changed_files() == {}
        assert "outside the git repository" in caplog.text

    def test_repo_root_outside_git(self, tmp_path, monkeypatch):
        """Outside any repository the working directory stands in for the root."""
        monkeypatch.chdir(tmp_path)
        failed = subprocess.CompletedProcess([], 128, stdout="", stderr="not a git repository")
        with patch("dbt_ci.utilities.git.subprocess.run", return_value=failed):
            assert GitAdapter._resolve_repo_root() == os.getcwd()


def test_blank_diff_rows_are_skipped():
    """An empty row in git's output (e.g. a trailing newline) is ignored."""
    adapter = _make_adapter([[""], [], ["M", "dbt/models/a.sql"]])
    assert adapter.get_changed_files() == {"modified": ["models/a.sql"]}
