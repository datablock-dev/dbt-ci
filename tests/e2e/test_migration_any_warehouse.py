"""
End-to-end checks of `migration` on a warehouse without layout config, and of the macro
that runs migration DDL, against real dbt and DuckDB.

DuckDB has no partitioning or clustering config, so a changed incremental model has
nothing to migrate: `migration` succeeds instead of failing for want of a connector.
The DDL dbt-ci renders for Snowflake, Redshift and Databricks runs through the
`dbt_ci_run_statements` macro; here it runs DuckDB statements, and a second dbt process
reading the result shows the statements were committed.

Like the other e2e tests, it is opt-in and runs against whichever dbt and runner the
environment selects (see dbt_env).
"""

import json
import shutil
import subprocess
from importlib import resources
from pathlib import Path

import pytest

from .dbt_env import DBT_AVAILABLE, SKIP_REASON, dbt_ci, run_dbt

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.requires_dbt,
    pytest.mark.skipif(not DBT_AVAILABLE, reason=SKIP_REASON),
]

DBT_PROJECT = 'name: demo\nversion: 1.0.0\nprofile: demo\nmodel-paths: ["models"]\n'
INCREMENTAL = "{{{{ config(materialized='incremental', {}) }}}}\nselect 1 as id\n"


def git(repo: Path, *args: str) -> None:
    """Run a git command in the repository."""
    subprocess.run(
        ["git", "-c", "user.email=ci@example.com", "-c", "user.name=ci", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def write_project(repo: Path, warehouse: Path) -> Path:
    """Write a DuckDB dbt project and return its directory."""
    dbt_dir = repo / "dbt"
    (dbt_dir / "models").mkdir(parents=True)
    (dbt_dir / "dbt_project.yml").write_text(DBT_PROJECT)
    (dbt_dir / "profiles.yml").write_text(
        "demo:\n"
        "  target: dev\n"
        "  outputs:\n"
        f"    dev: {{type: duckdb, path: '{warehouse}', schema: ci}}\n"
        f"    prod: {{type: duckdb, path: '{warehouse}', schema: main}}\n"
    )
    return dbt_dir


def test_migration_without_layout_config_succeeds(tmp_path: Path):
    """A changed incremental model on DuckDB has no layout to migrate, so it passes."""
    repo = tmp_path / "repo"
    dbt_dir = write_project(repo, tmp_path / "warehouse.duckdb")
    (dbt_dir / "models" / "events.sql").write_text(INCREMENTAL.format("unique_key='id'"))
    (repo / ".gitignore").write_text("target/\nlogs/\nstate/\n")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
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
        cwd=repo,
        mount=tmp_path,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    (repo / "state").mkdir()
    shutil.copy(dbt_dir / "target" / "manifest.json", repo / "state" / "manifest.json")
    shutil.rmtree(dbt_dir / "target")
    git(repo, "checkout", "-qb", "feature")
    (dbt_dir / "models" / "events.sql").write_text(
        INCREMENTAL.format("unique_key='id', partition_by='id'")
    )
    git(repo, "commit", "-qam", "partition events")

    cache = tmp_path / "cache"
    init = dbt_ci(
        repo,
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
    migration = dbt_ci(repo, cache, tmp_path, "migration")
    out = migration.stdout + migration.stderr
    assert migration.returncode == 0, out
    assert "No table layout changes" in out, out


def test_statements_run_and_are_committed(tmp_path: Path):
    """The macro runs each statement, and the result is there for the next dbt process."""
    dbt_dir = write_project(tmp_path / "repo", tmp_path / "warehouse.duckdb")
    (dbt_dir / "macros").mkdir()
    macro = resources.files("dbt_ci.dbt").joinpath("macros", "dbt_ci_operations.sql")
    (dbt_dir / "macros" / "dbt_ci_operations.sql").write_text(macro.read_text())

    def operation(*statements: str) -> subprocess.CompletedProcess:
        """Run dbt_ci_run_statements with the given statements."""
        return run_dbt(
            [
                "run-operation",
                "dbt_ci_run_statements",
                "--args",
                json.dumps({"statements": list(statements)}),
                "--project-dir",
                str(dbt_dir),
                "--profiles-dir",
                str(dbt_dir),
            ],
            cwd=dbt_dir,
            mount=tmp_path,
            check=False,
        )

    created = operation(
        "create schema if not exists ci",
        "create table ci.probe as select 1 as id",
        "alter table ci.probe add column note varchar",
    )
    assert created.returncode == 0, created.stdout + created.stderr
    # A new dbt process (and connection) sees the altered table
    read = operation("insert into ci.probe (id, note) values (2, 'kept')")
    assert read.returncode == 0, read.stdout + read.stderr
    failed = operation("alter table ci.missing add column x int")
    assert failed.returncode != 0
