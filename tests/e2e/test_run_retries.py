"""
End-to-end check of `run --retries` against real dbt.

A branch changes a model that fails on its first build and succeeds on the next, the
way a warehouse timeout would. Without --retries the run fails; with it, dbt-ci reruns
the failed model and the model downstream of it with `dbt retry`, and the run passes.

Like the other e2e tests, it is opt-in and runs against whichever dbt and runner the
environment selects (see dbt_env).
"""

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

# Writes a file per build before its query runs, and fails until it is built a second
# time. DuckDB writes the file outside the model's transaction, so a failed build still
# counts. A file rather than a table keeps it to hooks that dbt v1 and v2 both support.
FLAKY_MODEL = """\
{{ config(
    materialized="table",
    pre_hook="copy (select 1 as built) to 'ATTEMPTS/{{ invocation_id }}.csv'",
) }}
select case
    when (select count(*) from glob('ATTEMPTS/*.csv')) < 2 then error('transient failure')
    else 2
end as id
"""


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
    """A repo whose branch changes `a` into a model that fails on its first build."""
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
    (repo / ".gitignore").write_text("target/\nlogs/\nstate/\n")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")

    result = run_dbt(
        ["build", "--project-dir", str(dbt_dir), "--profiles-dir", str(dbt_dir)]
        + ["--target", "prod"],
        cwd=repo,
        mount=tmp_path,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    state = repo / "state"
    state.mkdir()
    shutil.copy(dbt_dir / "target" / "manifest.json", state / "manifest.json")
    shutil.rmtree(dbt_dir / "target")

    git(repo, "checkout", "-qb", "feature")
    attempts = tmp_path / "attempts"
    attempts.mkdir()
    (dbt_dir / "models" / "a.sql").write_text(FLAKY_MODEL.replace("ATTEMPTS", str(attempts)))
    git(repo, "commit", "-qam", "make a flaky")
    return repo


def init_and_run(project: Path, tmp_path: Path, *run_args: str):
    """Run init, then run with the given flags, and return run's result."""
    cache = tmp_path / "cache"
    init = dbt_ci(
        project,
        cache,
        tmp_path,
        "init",
        "--state",
        "state",
        "--reference-target",
        "prod",
        "--comparison-strategy",
        "dbt",
        "--compare-to",
        "latest",
    )
    assert init.returncode == 0, init.stdout + init.stderr
    return dbt_ci(project, cache, tmp_path, "run", "--mode", "models", *run_args)


def test_a_failed_step_fails_the_run_without_retries(project: Path, tmp_path: Path):
    """By default a failed step is not retried."""
    result = init_and_run(project, tmp_path)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "dbt retry" not in result.stdout + result.stderr


def test_retries_rerun_the_failed_nodes(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """
    dbt retry builds the model that failed and the one it skipped.

    DBT_STATE is set the way a `state` key in dbt-ci.config.yaml sets it. dbt reads it
    as --state too, and dbt retry would look for run_results.json there unless dbt-ci
    points it back at the target path.
    """
    monkeypatch.setenv("DBT_STATE", str(project / "state"))
    result = init_and_run(project, tmp_path, "--retries", "1")
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Retrying its failed and skipped nodes with dbt retry (retry 1 of 1)" in output

    run_results = (project / "dbt" / "target" / "run_results.json").read_text()
    assert '"model.demo.a"' in run_results and '"model.demo.b"' in run_results, run_results
