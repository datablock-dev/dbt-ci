"""Docker runner for dbt-ci"""
import os
from pathlib import Path
from subprocess import CompletedProcess
import sys
import docker
from docker import errors
from typing import List
from src.schema import RunnerConfig

def docker_runner(
    commands: List[str],
    runner_config: RunnerConfig
) -> CompletedProcess | None:
    """
    Execute dbt commands inside a Docker container.
    
    Args:
        commands: The dbt command and arguments to run
        dbt_project_dir: Absolute path to dbt project directory
        profiles_dir: Absolute path to profiles directory
        state_dir: Absolute path to state directory
        docker_image: Docker image to use
        docker_platform: Platform for Docker image (e.g., linux/amd64, linux/arm64). Use linux/amd64 on Apple Silicon for compatibility
        docker_volumes: Additional volume mounts
        docker_env: Environment variables to pass
        docker_network: Docker network mode
        docker_user: User to run as (UID:GID)
        docker_args: Additional docker run arguments
        dry_run: If True, only print the command
        quiet: If True, suppress stdout
    """
    try:
        cwd = Path.cwd()
        print(runner_config)
        return
        dbt_project_dir = runner_config.dbt_project_dir or "."
        docker_volumes = runner_config.docker_volumes or []
        docker_env = runner_config.docker_env or []

        # Auto-detect user if not specified
        if runner_config.docker_user is None:
            docker_user = f"{os.getuid()}:{os.getgid()}"

        if dry_run:
            print("DRY RUN: Command would be executed")
            return None
        if os.getenv("DBT_IMAGE", None) is not None:
            image = os.getenv("DBT_IMAGE")

        client = docker.client.from_env()
        
        # Build environment variables, excluding None values
        env_vars = {
            "DBT_PROFILES_DIR": "/dbt",
        }
        if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            env_vars["GOOGLE_APPLICATION_CREDENTIALS"] = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if os.getenv("USER"):
            env_vars["USER"] = os.getenv("USER")
        if os.getenv("GITHUB_SHA"):
            env_vars["GITHUB_SHA"] = os.getenv("GITHUB_SHA")
        if os.getenv("DBT_STATE"):
            env_vars["DBT_STATE"] = os.getenv("DBT_STATE")
        
        # Build volumes, excluding None paths
        volumes = {
            os.getenv("DBT_DIR", str((cwd / dbt_project_dir).resolve())): {"bind": "/dbt", "mode": "rw"}
        }
        if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            volumes[os.getenv("GOOGLE_APPLICATION_CREDENTIALS")] = {
                "bind": os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
                "mode": "ro",  # Keep credentials read-only for security
            }
        
        container = client.containers.run(
            image=docker_image,
            command=commands,
            detach=True,
            stdout=True,
            stderr=True,
            user=f"{os.getuid()}:{os.getgid()}",
            environment=env_vars,
            volumes=volumes
        )
        
        # Capture all logs as string
        output_logs = []
        for log in container.logs(stream=True):
            decoded = log.decode("utf-8")
            print(decoded, end="")
            output_logs.append(decoded)
        
        exit_status = container.wait()
        returncode = exit_status.get("StatusCode", 0)
        
        return CompletedProcess(
            args=commands, 
            returncode=returncode, 
            stdout="".join(output_logs), 
            stderr=""
        )
    except errors.ContainerError as e:
        print(f"Container error: {e}")
        sys.exit(1)
    except errors.ImageNotFound as e:
        print(f"Image not found: {e}")
        sys.exit(1)
    except errors.APIError as e:
        print(f"Docker API error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)