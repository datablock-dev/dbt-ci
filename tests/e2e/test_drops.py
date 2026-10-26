"""
End-to-end check that `delete` and `ephemeral destroy` drop relations on an adapter
without a native connector (DuckDB), through dbt's own adapter macros.

Like test_dbt_versions, it is opt-in and runs against whichever dbt and runner the
environment selects (see dbt_env). Production and the CI environment share one DuckDB
file in different schemas, as a warehouse would, so `dbt clone` can reach production.

The macros log every drop and every relation they find missing, so a second run
reporting a relation as missing proves the first one really dropped it. That keeps the
test independent of the duckdb version that wrote the file.
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
    branch removes the `legacy` model and changes `stg`.
    """
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
    (dbt_dir / "models" / "agg.sql").write_text("select count(*) as n from {{ ref('stg') }}\n")
    (dbt_dir / "models" / "legacy.sql").write_text("select 1 as x\n")
    (repo / ".gitignore").write_text("target/\nlogs/\nstate/\n")

    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")

    build = run_dbt(
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
    (dbt_dir / "models" / "stg.sql").write_text("select 2 as id\n")
    git(repo, "rm", "-q", "dbt/models/legacy.sql")
    git(repo, "commit", "-qam", "change stg, remove legacy")
    return repo


def output(result: subprocess.CompletedProcess) -> str:
    """Return everything a dbt-ci run printed."""
    return result.stdout + result.stderr


def init(project: Path, cache_dir: Path, tmp_path: Path) -> None:
    """Run init against the production state and check it succeeded."""
    result = dbt_ci(
        project,
        cache_dir,
        tmp_path,
        "init",
        "--state",
        "state",
        "--reference-target",
        "prod",
        "--base-ref",
        "main",
    )
    assert result.returncode == 0, output(result)


def test_delete_drops_the_removed_model(project: Path, tmp_path: Path):
    """delete drops the production table of the removed model, and only that one."""
    cache_dir = tmp_path / "cache"
    init(project, cache_dir, tmp_path)

    delete = dbt_ci(project, cache_dir, tmp_path, "delete", "--state", "state", target="prod")
    delete_output = output(delete)
    assert delete.returncode == 0, delete_output
    assert "dbt-ci: dropped" in delete_output and "legacy" in delete_output, delete_output
    assert "stg" not in delete_output.split("dbt-ci: dropped", 1)[1], delete_output

    # A second run finds nothing left to drop
    again = dbt_ci(project, cache_dir, tmp_path, "delete", "--state", "state", target="prod")
    assert again.returncode == 0, output(again)
    assert "main.legacy does not exist, skipping" in output(again), output(again)

    # The helper project stays out of the user's git status
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=project, capture_output=True, text=True
    )
    assert "dbt_ci_operations" not in status.stdout, status.stdout


def test_ephemeral_destroy_drops_the_ci_schema(project: Path, tmp_path: Path):
    """destroy drops the schema ephemeral cloned into, and refuses the production one."""
    cache_dir = tmp_path / "cache"
    init(project, cache_dir, tmp_path)

    create = dbt_ci(project, cache_dir, tmp_path, "ephemeral", "create", "--state", "state")
    if create.returncode != 0 and "materialization_view_duckdb" in output(create):
        # dbt v2 (2.0.9) cannot `dbt clone` on DuckDB at all: its clone materialization
        # dispatches to a view materialization the DuckDB adapter does not ship.
        pytest.skip(
            "dbt clone is broken on DuckDB in this dbt version, so there is nothing to tear down"
        )
    assert create.returncode == 0, output(create)

    destroy = dbt_ci(project, cache_dir, tmp_path, "ephemeral", "destroy", "--state", "state")
    destroy_output = output(destroy)
    assert destroy.returncode == 0, destroy_output
    # init compiles against the production target; the clone's own manifest still tells
    # destroy that the clones live in the `ci` schema
    assert 'dbt-ci: dropped schema "warehouse"."ci"' in destroy_output, destroy_output
    assert 'dropped schema "warehouse"."main"' not in destroy_output, destroy_output

    # Production is untouched: its table is still there for delete to drop
    delete = dbt_ci(project, cache_dir, tmp_path, "delete", "--state", "state", target="prod")
    assert delete.returncode == 0, output(delete)
    assert "dbt-ci: dropped" in output(delete) and "legacy" in output(delete), output(delete)
