"""
End-to-end check that `dbt-ci init` and `dbt-ci run` work against a real dbt binary.

The test is opt-in: set DBT_CI_E2E_DBT_BINARY to a dbt executable that can run DuckDB
(dbt-core with dbt-duckdb, or dbt v2, which bundles DuckDB). CI uses it to exercise
dbt v2 through the local runner, since dbt v2 cannot share an environment with the
dbt-core that dbt-ci itself depends on.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

DBT_BINARY = os.environ.get("DBT_CI_E2E_DBT_BINARY")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.requires_dbt,
    pytest.mark.skipif(not DBT_BINARY, reason="DBT_CI_E2E_DBT_BINARY is not set"),
]

DBT_PROJECT = """
name: demo
version: 1.0.0
profile: demo
model-paths: ["models"]
seed-paths: ["seeds"]
"""

SCHEMA = """
version: 2
models:
  - name: stg
    columns:
      - name: id
        data_tests: [not_null]
"""


def git(repo: Path, *args: str) -> None:
    """Run a git command in the given repository."""
    subprocess.run(
        ["git", "-c", "user.email=ci@example.com", "-c", "user.name=ci", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def dbt_ci(repo: Path, cache_dir: Path, *args: str) -> subprocess.CompletedProcess:
    """Run the dbt-ci CLI against the local runner and the dbt binary under test."""
    env = {**os.environ, "DBT_CI_CACHE_DIR": str(cache_dir)}
    return subprocess.run(
        [
            sys.executable, "-c", "from dbt_ci.main import cli; cli()", *args,
            "--runner", "local",
            "--entrypoint", str(DBT_BINARY),
            "--dbt-project-dir", "dbt",
            "--profiles-dir", "dbt",
            "--target", "dev",
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """
    Build a git repo whose main branch has production state and whose feature branch
    modifies one model.
    """
    repo = tmp_path / "repo"
    dbt_dir = repo / "dbt"
    (dbt_dir / "models").mkdir(parents=True)
    (dbt_dir / "seeds").mkdir()

    (dbt_dir / "dbt_project.yml").write_text(DBT_PROJECT)
    (dbt_dir / "profiles.yml").write_text(
        "demo:\n"
        "  target: dev\n"
        "  outputs:\n"
        f"    dev: {{type: duckdb, path: '{tmp_path / 'dev.duckdb'}'}}\n"
        f"    prod: {{type: duckdb, path: '{tmp_path / 'prod.duckdb'}'}}\n"
    )
    (dbt_dir / "seeds" / "raw.csv").write_text("id,name\n1,a\n2,b\n")
    (dbt_dir / "models" / "stg.sql").write_text("select * from {{ ref('raw') }}\n")
    (dbt_dir / "models" / "agg.sql").write_text("select count(*) as n from {{ ref('stg') }}\n")
    (dbt_dir / "models" / "other.sql").write_text("select 1 as x\n")
    (dbt_dir / "models" / "schema.yml").write_text(SCHEMA)
    (repo / ".gitignore").write_text("target/\nlogs/\ndbt_packages/\nstate/\n")

    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")

    # Production state: build main against the prod target and keep its manifest.
    subprocess.run(
        [str(DBT_BINARY), "build", "--project-dir", str(dbt_dir), "--profiles-dir", str(dbt_dir), "--target", "prod"],
        cwd=repo,
        check=True,
    )
    (repo / "state").mkdir()
    shutil.copy(dbt_dir / "target" / "manifest.json", repo / "state" / "manifest.json")
    shutil.rmtree(dbt_dir / "target")

    # The git comparison fetches the base branch from origin.
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(repo), str(origin)], check=True)
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "fetch", "-q", "origin")

    git(repo, "checkout", "-qb", "feature")
    (dbt_dir / "models" / "stg.sql").write_text("select id, upper(name) as name from {{ ref('raw') }}\n")
    git(repo, "commit", "-qam", "change stg")

    return repo


def test_init_and_run_detect_and_build_the_modified_model(project: Path, tmp_path: Path):
    """init finds exactly the changed model and run builds it plus its dependants."""
    cache_dir = tmp_path / "cache"

    init = dbt_ci(
        project, cache_dir, "init",
        "--state", "state",
        "--reference-target", "prod",
        "--base-ref", "main",
    )
    init_output = init.stdout + init.stderr
    assert init.returncode == 0, init_output
    assert "Modified Nodes: 1" in init_output, init_output
    assert "stg [model]" in init_output, init_output

    run = dbt_ci(project, cache_dir, "run", "--state", "state")
    run_output = run.stdout + run.stderr
    assert run.returncode == 0, run_output
    assert "Successfully ran 2 models(s)" in run_output, run_output
