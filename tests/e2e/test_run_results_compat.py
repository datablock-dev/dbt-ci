"""
End-to-end check that dbt-ci reads run_results.json from real dbt, state_decision_id or not.

dbt-core 1.12.7 added `state_decision_id` to its run results: dbt State's id for the
decision to build or reuse a node. Open-source dbt-core keeps it on the in-memory result
and in its event logs, and dbt State or later versions may write it into
run_results.json too. dbt-ci reads that file after each dbt command to record node
times, so this checks two things:

- `run` records the times of the real run_results.json the dbt under test writes,
  whatever fields that version puts in it.
- The same file, with a `state_decision_id` added to every result, gives the same
  times: the field is safely ignored.

Like the other e2e tests, it is opt-in and runs against whichever dbt and runner the
environment selects (see dbt_env).
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from dbt_ci.utilities.run_times import read_node_times

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
    """A repo with production state whose feature branch changes one model."""
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
        ["compile", "--project-dir", str(dbt_dir), "--profiles-dir", str(dbt_dir)]
        + ["--target", "prod"],
        cwd=repo,
        mount=tmp_path,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    (repo / "state").mkdir()
    (dbt_dir / "target" / "manifest.json").rename(repo / "state" / "manifest.json")

    git(repo, "checkout", "-qb", "feature")
    (dbt_dir / "models" / "a.sql").write_text("select 2 as id\n")
    git(repo, "commit", "-qam", "change a")
    return repo


def generated_at(run_results: dict) -> datetime:
    """Return when dbt wrote run_results.json."""
    return datetime.fromisoformat(run_results["metadata"]["generated_at"].replace("Z", "+00:00"))


def test_run_results_are_read_with_or_without_state_decision_id(project: Path, tmp_path: Path):
    """run records the real file's times, and an added state_decision_id changes nothing."""
    cache = tmp_path / "cache"
    for command in (
        ["init", "--state", "state", "--reference-target", "prod"]
        + ["--comparison-strategy", "dbt", "--compare-to", "latest"],
        ["run", "--mode", "models"],
    ):
        result = dbt_ci(project, cache, tmp_path, *command)
        assert result.returncode == 0, result.stdout + result.stderr

    dbt_dir = project / "dbt"
    path = dbt_dir / "target" / "run_results.json"
    written = json.loads(path.read_text())
    built = {r["unique_id"] for r in written["results"]}
    assert {"model.demo.a", "model.demo.b"} <= built, built
    # Whatever this dbt writes for the field, it is a string id or null
    for entry in written["results"]:
        assert isinstance(entry.get("state_decision_id"), (str, type(None))), entry

    # run recorded the times from the file the dbt under test wrote
    recorded = json.loads((cache / "run_times.json").read_text())["this_run"]
    assert set(recorded) == {
        r["unique_id"] for r in written["results"] if (r.get("execution_time") or 0) > 0
    }, recorded

    since = generated_at(written)
    expected = read_node_times(str(dbt_dir), since)
    assert expected, written

    with_ids = {
        **written,
        "results": [
            {**entry, "state_decision_id": f"sd-{n}"} for n, entry in enumerate(written["results"])
        ],
    }
    path.write_text(json.dumps(with_ids))
    assert read_node_times(str(dbt_dir), since) == expected
