"""Docker runner for dbt-ci"""
import os
import sys
from subprocess import CompletedProcess
import docker
from docker import errors
from dbt_ci.schema import RunnerConfig
from dbt_ci.utilities.paths import get_absolute_path

def docker_runner(commands: list[str], runner_config: RunnerConfig) -> CompletedProcess | None:
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
            volumes=get_docker_volumes(runner_config),
            #network_mode=runner_config.get("docker_network", "bridge")
        )
        
        # Capture all logs as string
        output_logs = []
        for log in container.logs(stream=True):
            decoded = log.decode("utf-8")
            sys.stdout.write(decoded)
            sys.stdout.flush()
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

def parse_docker_env(runner_config: RunnerConfig) -> dict:
    """Parse docker_env list into a dictionary."""
    env_dict = {}
    docker_env = runner_config.get("docker_env", [])
    if docker_env:
        for env in docker_env:
            if "=" in env:
                key, value = env.split("=", 1)
                env_dict[key] = value
    return env_dict

def parse_docker_volumes(runner_config: RunnerConfig) -> dict:
    """Parse docker_volumes list into a host_path -> container_path mapping."""
    volume_map = {}
    docker_volumes = runner_config.get("docker_volumes", [])
    for volume in docker_volumes:
        parts = volume.split(":", 2)
        if len(parts) >= 2:
            host_path = parts[0]
            container_path = parts[1]
            volume_map[host_path] = container_path
    return volume_map

def get_container_paths(runner_config: RunnerConfig) -> dict:
    """Get container paths for dbt configuration variables.
    
    Returns a mapping of variable names to their container paths:
    {
        'dbt_project_dir': '/dbt',
        'profiles_dir': '/dbt',
        'reference_state': '/dbt/.dbtstate'
    }
    """
    env_dict = parse_docker_env(runner_config)
    volume_map = parse_docker_volumes(runner_config)
    
    container_path_map = {}
    
    # For dbt_project_dir: use DBT_PROJECT_DIR env or derive from volume mapping
    if "DBT_PROJECT_DIR" in env_dict:
        container_path_map["dbt_project_dir"] = env_dict["DBT_PROJECT_DIR"]
    else:
        # Try to derive from volume mapping
        dbt_project_host = runner_config.get("dbt_project_dir")
        if dbt_project_host and dbt_project_host in volume_map:
            container_path_map["dbt_project_dir"] = volume_map[dbt_project_host]
    
    # For profiles_dir: use DBT_PROFILES_DIR env
    if "DBT_PROFILES_DIR" in env_dict:
        container_path_map["profiles_dir"] = env_dict["DBT_PROFILES_DIR"]
    
    # For reference_state: use DBT_STATE env (translated through volume map) or derive from volume mapping
    reference_state_host = env_dict.get("DBT_STATE") or runner_config.get("reference_state")
    if reference_state_host:
        reference_state_abs = get_absolute_path(reference_state_host)
        # Translate host path to container path via volume map
        for host_mount, container_mount in volume_map.items():
            host_mount_abs = get_absolute_path(host_mount)
            if reference_state_abs.startswith(host_mount_abs):
                relative_path = reference_state_abs[len(host_mount_abs):].lstrip('/')
                container_path_map["reference_state"] = f"{container_mount}/{relative_path}" if relative_path else container_mount
                break
        else:
            # No volume match — use as-is (e.g. already an absolute container path)
            container_path_map["reference_state"] = reference_state_host
    
    return container_path_map

def get_docker_env(runner_config: RunnerConfig) -> dict | None:
    """Build Docker environment variables based on runner configuration."""
    # Don't automatically set environment variables - let the command-line flags handle paths
    # and only use user-provided docker_env
    env_dict = {}
    
    # Only use user-provided docker_env
    user_env = parse_docker_env(runner_config)
    env_dict.update(user_env)
    
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
