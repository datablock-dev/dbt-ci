"""
How the e2e tests reach dbt: a local binary, or a Docker image through the Docker runner.

- DBT_CI_E2E_DBT_BINARY: a dbt executable that can run DuckDB. dbt-ci drives it with
  the local runner.
- DBT_CI_E2E_DOCKER_IMAGE: an image whose entrypoint is dbt (see docker/Dockerfile).
  dbt-ci drives it with the Docker runner, and takes precedence over the binary.
- DBT_CI_E2E_REFERENCE_DBT_BINARY: optional dbt executable used to build the
  production state instead, e.g. dbt-core 1.x while the PR runs dbt v2.

Tests mount their temporary directory into the container at the same path, so paths
in profiles.yml, the project and the state are identical inside and outside it.
"""
import os
import subprocess
import sys
from pathlib import Path

DBT_BINARY = os.environ.get("DBT_CI_E2E_DBT_BINARY")
DOCKER_IMAGE = os.environ.get("DBT_CI_E2E_DOCKER_IMAGE")
REFERENCE_DBT_BINARY = os.environ.get("DBT_CI_E2E_REFERENCE_DBT_BINARY")

DBT_AVAILABLE = bool(DOCKER_IMAGE or DBT_BINARY)
SKIP_REASON = "neither DBT_CI_E2E_DOCKER_IMAGE nor DBT_CI_E2E_DBT_BINARY is set"


def docker_run_prefix(mount: Path, workdir: Path) -> list[str]:
    """Return the `docker run` arguments that run the test image as the current user."""
    return [
        "docker", "run", "--rm",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "--env", "HOME=/tmp",
        "--network", "host",
        "--volume", f"{mount}:{mount}",
        "--workdir", str(workdir),
        str(DOCKER_IMAGE),
    ]


def run_dbt(
    args: list[str],
    cwd: Path,
    mount: Path,
    binary: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run dbt directly, with an explicit binary, the test image or the test binary."""
    if binary:
        command = [binary, *args]
    elif DOCKER_IMAGE:
        command = [*docker_run_prefix(mount, cwd), *args]
    else:
        command = [str(DBT_BINARY), *args]
    return subprocess.run(command, cwd=cwd, check=check, capture_output=True, text=True)


def runner_args(mount: Path, profiles_dir: Path) -> list[str]:
    """Return the dbt-ci flags that select the runner under test."""
    if DOCKER_IMAGE:
        return [
            "--runner", "docker",
            "--docker-image", str(DOCKER_IMAGE),
            "--docker-volumes", f"{mount}:{mount}",
            "--docker-env", f"DBT_PROFILES_DIR={profiles_dir}",
            "--docker-env", "HOME=/tmp",
        ]
    return ["--runner", "local", "--entrypoint", str(DBT_BINARY)]


def dbt_ci(repo: Path, cache_dir: Path, mount: Path, *args: str) -> subprocess.CompletedProcess:
    """Run the dbt-ci CLI against the runner and dbt under test."""
    env = {**os.environ, "DBT_CI_CACHE_DIR": str(cache_dir)}
    return subprocess.run(
        [
            sys.executable, "-c", "from dbt_ci.main import cli; cli()", *args,
            *runner_args(mount, repo / "dbt"),
            "--dbt-project-dir", "dbt",
            "--profiles-dir", "dbt",
            "--target", "dev",
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
