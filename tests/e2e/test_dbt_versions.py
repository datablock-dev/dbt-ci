"""
End-to-end check that `dbt-ci init` and `dbt-ci run` work against a real dbt.

The test is opt-in: see dbt_env for the environment variables that pick the dbt under
test. CI runs it with the local runner against dbt-core 1.x and dbt v2, and with the
Docker runner against dbt-core 1.x and dbt v2 images. dbt v2 cannot share an
environment with the dbt-core that dbt-ci itself depends on, so it always runs from
its own venv or image.

With DBT_CI_E2E_REFERENCE_DBT_BINARY set, the production state is built with that dbt
(e.g. dbt-core 1.x) while the PR runs the dbt under test (e.g. dbt v2). That is the
mid-upgrade case, where the stored state manifest predates the new dbt version.
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
        project, cache_dir, tmp_path, "init",
        "--state", "state",
        "--reference-target", "prod",
        "--base-ref", "main",
    )
    init_output = init.stdout + init.stderr
    assert init.returncode == 0, init_output
    assert "Modified Nodes: 1" in init_output, init_output
    assert "stg [model]" in init_output, init_output

    run = dbt_ci(project, cache_dir, tmp_path, "run", "--state", "state")
    run_output = run.stdout + run.stderr
    assert run.returncode == 0, run_output
    assert "Successfully ran 2 models(s)" in run_output, run_output
