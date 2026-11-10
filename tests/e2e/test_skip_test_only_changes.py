"""
End-to-end check of `run --skip-test-only-changes` against real dbt and git.

Production built `a` and `b` (which reads `a`). A branch only adds a test on `a` in its
YAML file, which the git strategy marks as a change to `a`. With the option, `run`
runs the new test against production through --defer and rebuilds neither `a` nor `b`;
without it, both models are rebuilt.

Like the other e2e tests, it is opt-in and runs against whichever dbt and runner the
environment selects (see dbt_env).
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from .dbt_env import DBT_AVAILABLE, SKIP_REASON, dbt_ci, run_dbt

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.requires_dbt,
    pytest.mark.skipif(not DBT_AVAILABLE, reason=SKIP_REASON),
]

DBT_PROJECT = 'name: demo\nversion: 1.0.0\nprofile: demo\nmodel-paths: ["models"]\n'
SCHEMA = "version: 2\nmodels:\n  - name: a\n    columns:\n      - name: id\n"
SCHEMA_WITH_TEST = SCHEMA + "        data_tests:\n          - not_null\n"


def git(repo: Path, *args: str) -> None:
    """Run a git command in the repository."""
    subprocess.run(
        ["git", "-c", "user.email=ci@example.com", "-c", "user.name=ci", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A repo built in production, on a branch that only adds a test to `a`."""
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
    (dbt_dir / "models" / "a.sql").write_text("select 1 as id\n")
    (dbt_dir / "models" / "b.sql").write_text("select id from {{ ref('a') }}\n")
    (dbt_dir / "models" / "schema.yml").write_text(SCHEMA)
    (repo / ".gitignore").write_text("target/\nlogs/\nstate/\n")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(repo), str(origin)], check=True)
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "fetch", "-q", "origin")

    result = run_dbt(
        [
            "build",
            "--project-dir",
            str(dbt_dir),
            "--profiles-dir",
            str(dbt_dir),
            "--target",
            "prod",
        ],
        cwd=repo,
        mount=tmp_path,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    (repo / "state").mkdir()
    shutil.copy(dbt_dir / "target" / "manifest.json", repo / "state" / "manifest.json")
    shutil.rmtree(dbt_dir / "target")

    git(repo, "checkout", "-qb", "feature")
    (dbt_dir / "models" / "schema.yml").write_text(SCHEMA_WITH_TEST)
    git(repo, "commit", "-qam", "test a")
    return repo


def init_and_run(project: Path, tmp_path: Path, *run_flags: str) -> dict[str, float]:
    """Run init with the git strategy and then run; return the nodes run built."""
    cache = tmp_path / "cache"
    for command in (
        ["init", "--state", "state", "--reference-target", "prod"]
        + ["--comparison-strategy", "git", "--base-ref", "main", "--compare-to", "latest"],
        ["run", "--defer", *run_flags],
    ):
        result = dbt_ci(project, cache, tmp_path, *command)
        assert result.returncode == 0, result.stdout + result.stderr
    return json.loads((cache / "run_times.json").read_text())["this_run"]


def test_only_the_new_test_runs(project: Path, tmp_path: Path):
    """With the option, the new test runs and neither model is rebuilt."""
    built = init_and_run(project, tmp_path, "--skip-test-only-changes")
    assert not any(node.startswith("model.") for node in built), built
    assert any(node.startswith("test.demo.not_null_a_id") for node in built), built

    reasons = json.loads((tmp_path / "cache" / "cache.json").read_text())["reasons"]
    assert any("only its tests changed" in reason for reason in reasons["model.demo.a"])


def test_without_the_option_the_model_is_rebuilt(project: Path, tmp_path: Path):
    """By default the change to a's YAML file rebuilds a and what reads it."""
    built = init_and_run(project, tmp_path)
    assert {"model.demo.a", "model.demo.b"} <= set(built), built
