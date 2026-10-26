"""
End-to-end check that a PR changing only seeds and their tests goes through `init`,
`ephemeral create` and `run`.

Such a change selects no model or snapshot, so `ephemeral` has nothing to clone and
must skip `dbt clone` rather than call it with an empty `--select`. `run` then seeds
the new seed and tests it on its own.

Like test_dbt_versions, it is opt-in and runs against whichever dbt and runner the
environment selects (see dbt_env). Production and the CI environment share one DuckDB
file in different schemas, as a warehouse would.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

from .dbt_env import DBT_AVAILABLE, REFERENCE_DBT_BINARY, SKIP_REASON, dbt_ci, run_dbt

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.requires_dbt,
    pytest.mark.skipif(not DBT_AVAILABLE, reason=SKIP_REASON),
]

DBT_PROJECT = """
name: demo
version: 1.0.0
profile: demo
model-paths: ["models"]
seed-paths: ["seeds"]
"""

SEED_SCHEMA = """
version: 2
seeds:
  - name: items
    columns:
      - name: id
        data_tests: [not_null, unique]
"""


def git(repo: Path, *args: str) -> None:
    """Run a git command in the given repository."""
    subprocess.run(
        ["git", "-c", "user.email=ci@example.com", "-c", "user.name=ci", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """
    Build a repo whose main branch is deployed to the `main` schema and whose feature
    branch only adds the `items` seed with two tests on it.
    """
    repo = tmp_path / "repo"
    dbt_dir = repo / "dbt"
    (dbt_dir / "models").mkdir(parents=True)
    (dbt_dir / "seeds").mkdir()
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
    (repo / ".gitignore").write_text("target/\nlogs/\nstate/\n")

    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")

    build = run_dbt(
        ["build", "--project-dir", str(dbt_dir), "--profiles-dir", str(dbt_dir), "--target", "prod"],
        cwd=repo,
        mount=tmp_path,
        binary=REFERENCE_DBT_BINARY,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    (repo / "state").mkdir()
    shutil.copy(dbt_dir / "target" / "manifest.json", repo / "state" / "manifest.json")
    shutil.rmtree(dbt_dir / "target")

    origin = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(repo), str(origin)], check=True)
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "fetch", "-q", "origin")

    git(repo, "checkout", "-qb", "feature")
    (dbt_dir / "seeds" / "items.csv").write_text("id,name\n1,a\n2,b\n")
    (dbt_dir / "seeds" / "schema.yml").write_text(SEED_SCHEMA)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "add items seed")
    return repo


def output(result: subprocess.CompletedProcess) -> str:
    """Return everything a dbt-ci run printed."""
    return result.stdout + result.stderr


def test_seed_only_change_skips_clone_and_runs_the_seed(project: Path, tmp_path: Path):
    """ephemeral skips dbt clone for a seed-only change, and run still seeds and tests the seed."""
    cache_dir = tmp_path / "cache"

    init = dbt_ci(
        project, cache_dir, tmp_path, "init",
        "--state", "state", "--reference-target", "prod", "--base-ref", "main",
    )
    assert init.returncode == 0, output(init)
    assert "items [seed]" in output(init), output(init)

    create = dbt_ci(project, cache_dir, tmp_path, "ephemeral", "create", "--state", "state")
    create_output = output(create)
    assert create.returncode == 0, create_output
    assert "No models or snapshots to clone" in create_output, create_output

    run = dbt_ci(project, cache_dir, tmp_path, "run", "--state", "state")
    run_output = output(run)
    assert run.returncode == 0, run_output
    assert "Successfully ran 1 seeds(s)" in run_output, run_output
    assert "Successfully ran 2 tests(s)" in run_output, run_output
