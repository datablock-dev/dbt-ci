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
        if runner_config.get("dry_run", False):
            print("DRY RUN: Command would be executed")
            return None

        client = docker.client.from_env()
        container = client.containers.run(
            image=runner_config.get("docker_image", "ghcr.io/dbt-labs/dbt-core:latest"),
            command=commands,
            detach=True,
            stdout=True,
            stderr=True,
            user=runner_config.get("docker_user", f"{os.getuid()}:{os.getgid()}"),
            environment=get_docker_env(runner_config),
            volumes=get_docker_volumes(runner_config)
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

def get_docker_env(runner_config: RunnerConfig) -> dict | None:
    """Build Docker environment variables based on runner configuration."""
    if runner_config.get("docker_env", None) is None or len(runner_config["docker_env"]) == 0:
        return None
    
    env_dict = {}
    for env in runner_config.get("docker_env", []):
        key, value = env.split("=", 1)
        env_dict[key] = value
    return env_dict


def get_docker_volumes(runner_config: RunnerConfig) -> dict | None:
    """Build Docker volume bindings based on runner configuration."""
    if runner_config.get("docker_volumes", None) is None or len(runner_config["docker_volumes"]) == 0:
        return None

    cwd = Path.cwd()
    volume_dict = {}
    for volume in runner_config.get("docker_volumes", []):
        parts = volume.split(":", 2)
        host_path = parts[0]
        container_path = parts[1]
        mode = parts[2] if len(parts) == 3 else "rw"
        if not os.path.isabs(host_path):
            host_path = str((cwd / host_path).resolve())
        volume_dict[host_path] = {
            "bind": container_path, 
            "mode": mode
        }
    return volume_dict
