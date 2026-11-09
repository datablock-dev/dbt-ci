"""
End-to-end check of `init --baseline merge-base` against real dbt and git.

The feature branch changes `stg`. After it was created, someone else merged a change to
`other` into main and deployed it, so the production state includes the new `other`.
Compared against the latest state, `other` shows up as part of the pull request; compared
against the merge base (archived or compiled), only `stg` does.

Like the other e2e tests, it is opt-in and runs against whichever dbt and runner the
environment selects (see dbt_env).
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from .dbt_env import DBT_AVAILABLE, DOCKER_IMAGE, REFERENCE_DBT_BINARY, SKIP_REASON, dbt_ci, run_dbt

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.requires_dbt,
    pytest.mark.skipif(not DBT_AVAILABLE, reason=SKIP_REASON),
]

DBT_PROJECT = 'name: demo\nversion: 1.0.0\nprofile: demo\nmodel-paths: ["models"]\n'


def git(repo: Path, *args: str) -> str:
    """Run a git command in the given repository and return its output."""
    result = subprocess.run(
        ["git", "-c", "user.email=ci@example.com", "-c", "user.name=ci", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def parse_for_prod(project: Path, mount: Path) -> Path:
    """Parse a project for the prod target and return its manifest."""
    dbt_dir = project / "dbt"
    result = run_dbt(
        [
            "parse",
            "--project-dir",
            str(dbt_dir),
            "--profiles-dir",
            str(dbt_dir),
            "--target",
            "prod",
        ],
        cwd=project,
        mount=mount,
        binary=REFERENCE_DBT_BINARY,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return dbt_dir / "target" / "manifest.json"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Build the repo, the archived merge-base manifest and a production state that moved on."""
    repo = tmp_path / "repo"
    dbt_dir = repo / "dbt"
    (dbt_dir / "models").mkdir(parents=True)
    (dbt_dir / "dbt_project.yml").write_text(DBT_PROJECT)
    warehouse = tmp_path / "warehouse.duckdb"
    (dbt_dir / "profiles.yml").write_text(
        "demo:\n"
        "  target: dev\n"
        "  outputs:\n"
        f"    dev: {{type: duckdb, path: '{warehouse}', schema: ci}}\n"
        f"    prod: {{type: duckdb, path: '{warehouse}', schema: main}}\n"
    )
    (dbt_dir / "models" / "stg.sql").write_text("select 1 as id\n")
    (dbt_dir / "models" / "other.sql").write_text("select 1 as x\n")
    (repo / ".gitignore").write_text("target/\nlogs/\nstate/\n.dbtstate-baseline/\n")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    merge_base = git(repo, "rev-parse", "HEAD")

    # The deploy of the base commit archived its manifest under the commit's SHA
    archive = tmp_path / "archive" / merge_base
    archive.mkdir(parents=True)
    shutil.copy(parse_for_prod(repo, tmp_path), archive / "manifest.json")
    shutil.rmtree(dbt_dir / "target")

    origin = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(repo), str(origin)], check=True)
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "fetch", "-q", "origin")
    git(repo, "checkout", "-qb", "feature")
    (dbt_dir / "models" / "stg.sql").write_text("select 2 as id\n")
    git(repo, "commit", "-qam", "change stg")

    # Meanwhile someone merges a change to `other` into main, and it is deployed
    elsewhere = tmp_path / "elsewhere"
    subprocess.run(["git", "clone", "-q", str(origin), str(elsewhere)], check=True)
    (elsewhere / "dbt" / "models" / "other.sql").write_text("select 2 as x\n")
    git(elsewhere, "commit", "-qam", "change other")
    git(elsewhere, "push", "-q", "origin", "main")
    (repo / "state").mkdir()
    shutil.copy(parse_for_prod(elsewhere, tmp_path), repo / "state" / "manifest.json")
    return repo


def init(project: Path, tmp_path: Path, *extra: str) -> str:
    """Run init with the dbt strategy against the moved-on production state."""
    result = dbt_ci(
        project,
        tmp_path / "cache",
        tmp_path,
        "init",
        "--state",
        "state",
        "--reference-target",
        "prod",
        "--comparison-strategy",
        "dbt",
        "--base-ref",
        "main",
        *extra,
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    return out


def test_latest_state_counts_other_peoples_changes(project: Path, tmp_path: Path):
    """Without a baseline, the change merged into main shows up as the PR's own."""
    out = init(project, tmp_path)
    assert "stg [model]" in out, out
    assert "other [model]" in out, out


def test_archived_merge_base_leaves_them_out(project: Path, tmp_path: Path):
    """Against the manifest archived for the merge base, only the PR's change counts."""
    template = str(tmp_path / "archive" / "{sha}" / "manifest.json")
    out = init(project, tmp_path, "--baseline", "merge-base", "--baseline-uri", template)
    assert "Comparing against the manifest archived for the merge base" in out, out
    assert "stg [model]" in out, out
    assert "other [model]" not in out, out


@pytest.mark.skipif(bool(DOCKER_IMAGE), reason="compiling the merge base needs a host runner")
def test_compiled_merge_base_leaves_them_out(project: Path, tmp_path: Path):
    """Without an archive, the merge base is compiled and only the PR's change counts."""
    out = init(project, tmp_path, "--baseline", "merge-base")
    assert "compiled for this run" in out, out
    assert "stg [model]" in out, out
    assert "other [model]" not in out, out
    assert git(project, "worktree", "list").count("\n") == 0, "temporary worktree left behind"
