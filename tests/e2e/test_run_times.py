"""
End-to-end check of the report's run time section against real dbt.

Production was built in full, and its node times were kept next to the state as
run_times.json (what finalize publishes). A branch changes one model: `run` builds only
that model, records its time from dbt's run_results.json, and the report compares it
with the recorded time of the models it left out.

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
    """A repo whose production build's node times are kept next to the state."""
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
    (dbt_dir / "models" / "c.sql").write_text("select 1 as x\n")
    (repo / ".gitignore").write_text("target/\nlogs/\nstate/\n")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")

    # Production builds everything; its manifest and node times become the state
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
    state = repo / "state"
    state.mkdir()
    shutil.copy(dbt_dir / "target" / "manifest.json", state / "manifest.json")
    run_results = json.loads((dbt_dir / "target" / "run_results.json").read_text())
    nodes = {r["unique_id"]: r["execution_time"] or 0.001 for r in run_results["results"]}
    (state / "run_times.json").write_text(json.dumps({"nodes": nodes}))
    shutil.rmtree(dbt_dir / "target")

    git(repo, "checkout", "-qb", "feature")
    (dbt_dir / "models" / "c.sql").write_text("select 2 as x\n")
    git(repo, "commit", "-qam", "change c")
    return repo


def test_report_shows_run_time_and_what_was_skipped(project: Path, tmp_path: Path):
    """The report counts what this run built and the recorded time of what it left out."""
    cache = tmp_path / "cache"
    common = ["--state", "state"]
    for command in (
        ["init", *common, "--reference-target", "prod", "--comparison-strategy", "dbt"]
        + ["--compare-to", "latest"],
        ["run", "--mode", "models"],
        ["report", "--output", str(tmp_path / "report.md")],
    ):
        result = dbt_ci(project, cache, tmp_path, *command)
        assert result.returncode == 0, result.stdout + result.stderr

    measured = json.loads((cache / "run_times.json").read_text())
    assert list(measured["this_run"]) == ["model.demo.c"], measured
    assert {"model.demo.a", "model.demo.b"} <= set(measured["recorded"]), measured

    report = (tmp_path / "report.md").read_text()
    assert "### Run time" in report, report
    assert "Built **1** node(s)" in report, report
    assert "The **2** other node(s) with a recorded run time" in report, report
