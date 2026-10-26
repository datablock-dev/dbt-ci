"""
Build a throwaway dbt + DuckDB repository for smoke-testing the GitHub Action.

The repository has production state built from `main` (in `state/`), a bare `origin`
the git comparison can fetch from, and a checked-out `feature` branch that modifies the
`stg` model. Running the action there should detect exactly one modified model.

Usage: python tests/action/make_demo_project.py <directory>   (needs dbt-duckdb on PATH)
"""

import shutil
import subprocess
import sys
from pathlib import Path

FILES = {
    "dbt/dbt_project.yml": "name: demo\nversion: 1.0.0\nprofile: demo\nmodel-paths: [models]\nseed-paths: [seeds]\n",
    "dbt/seeds/raw.csv": "id,name\n1,a\n2,b\n",
    "dbt/models/stg.sql": "select * from {{ ref('raw') }}\n",
    "dbt/models/agg.sql": "select count(*) as n from {{ ref('stg') }}\n",
    "dbt/models/other.sql": "select 1 as x\n",
    "dbt/models/schema.yml": (
        "version: 2\nmodels:\n  - name: stg\n    columns:\n      - name: id\n        data_tests: [not_null]\n"
    ),
    ".gitignore": "target/\nlogs/\ndbt_packages/\n",
}


def git(repo: Path, *args: str) -> None:
    """Run a git command in the repository."""
    subprocess.run(
        ["git", "-c", "user.email=ci@example.com", "-c", "user.name=ci", *args],
        cwd=repo,
        check=True,
    )


def make_demo_project(root: Path) -> Path:
    """Create the demo repository under root and return its path."""
    repo = root / "repo"
    for name, content in FILES.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    (repo / "dbt" / "profiles.yml").write_text(
        "demo:\n"
        "  target: dev\n"
        "  outputs:\n"
        f"    dev: {{type: duckdb, path: '{root / 'dev.duckdb'}'}}\n"
        f"    prod: {{type: duckdb, path: '{root / 'prod.duckdb'}'}}\n"
    )

    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")

    # Production state, as a deploy job would store it.
    subprocess.run(
        ["dbt", "build", "--project-dir", "dbt", "--profiles-dir", "dbt", "--target", "prod"],
        cwd=repo,
        check=True,
    )
    (repo / "state").mkdir()
    shutil.copy(repo / "dbt" / "target" / "manifest.json", repo / "state" / "manifest.json")
    shutil.rmtree(repo / "dbt" / "target")

    subprocess.run(
        ["git", "clone", "-q", "--bare", str(repo), str(root / "origin.git")], check=True
    )
    git(repo, "remote", "add", "origin", str(root / "origin.git"))
    git(repo, "fetch", "-q", "origin")

    git(repo, "checkout", "-qb", "feature")
    (repo / "dbt" / "models" / "stg.sql").write_text(
        "select id, upper(name) as name from {{ ref('raw') }}\n"
    )
    git(repo, "commit", "-qam", "change stg")
    return repo


if __name__ == "__main__":
    print(make_demo_project(Path(sys.argv[1]).resolve()))
