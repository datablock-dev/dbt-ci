"""Docker runner for dbt-ci"""
import os
from pathlib import Path
from subprocess import CompletedProcess
import sys
import docker
from docker import errors
from typing import List
from src.schema import RunnerConfig
from src.utilities.paths import get_absolute_path

def docker_runner(commands: List[str], runner_config: RunnerConfig) -> CompletedProcess | None:
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
        if returncode != 0:
            print("".join(output_logs))
            sys.exit(1)

        # Optionally filter dbt log lines from output
        stdout = "".join(output_logs)

        """
        if filter_output:
            # Filter out dbt log lines - only keep actual command output
            # Node names/output don't contain ANSI escape codes or log keywords
            all_lines = stdout.strip().split("\n")
            filtered_lines = [
                line.strip()
                for line in all_lines
                if line.strip() and
                   not line.startswith('\x1b') and  # ANSI escape codes
                   not any(keyword in line for keyword in [
                       '[', ']', 
                       ':',
                       'Running',
                       'WARNING',
                       'Found',
                       'INFO', 
                       'Completed',
                       'Done',
                       'with',
                       'ERROR'
                   ])
            ]
            stdout = "\n".join(filtered_lines)
        """
        
        return CompletedProcess(
            args=commands,
            returncode=returncode,
            stdout=stdout,
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
    # Automatically translate certain flags/configs to 
    # environment variables for better Docker compatibility
    env_dict = {}
    config_to_env = {
        "dbt_project_dir": "DBT_PROJECT_DIR",
        "profiles_dir": "DBT_PROFILES_DIR",
        "reference_state": "DBT_REFERENCE_STATE",
    }

    for config_key, env_key in config_to_env.items():
        if runner_config.get(config_key, None) is not None:
            env_dict[env_key] = runner_config[config_key]

    docker_env = runner_config.get("docker_env", [])
    if docker_env:
        for env in docker_env:
            key, value = env.split("=", 1)
            env_dict[key] = value
    
    return env_dict


def get_docker_volumes(runner_config: RunnerConfig) -> dict | None:
    """Build Docker volume bindings based on runner configuration."""
    volume_dict = {}
    if runner_config.get("docker_volumes", None) is None or len(runner_config["docker_volumes"]) == 0:
        return None
    
    for volume in runner_config.get("docker_volumes", []):
        parts = volume.split(":", 2)
        host_path = get_absolute_path(parts[0])
        container_path = parts[1]
        mode = parts[2] if len(parts) == 3 else "rw"
        volume_dict[host_path] = {
            "bind": container_path, 
            "mode": mode
        }
    return volume_dict
