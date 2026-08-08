"""Docker runner for dbt-ci"""
import logging
import os
import shlex
import sys
from subprocess import CompletedProcess
from typing import Any, cast
import docker
from docker import errors
from docker.models.containers import Container
from dbt_ci.schema import RunnerConfig
from dbt_ci.utilities.logging import redact
from dbt_ci.utilities.paths import get_absolute_path

logger = logging.getLogger(__name__)

def docker_runner(commands: list[str], runner_config: RunnerConfig) -> CompletedProcess | None:
    """
    Execute dbt commands inside a Docker container.

    Reads the following keys from runner_config:
        docker_image: Docker image to use
        docker_platform: Platform for Docker image (e.g., linux/amd64, linux/arm64). Use linux/amd64 on Apple Silicon for compatibility
        docker_volumes: Volume mounts (host:container[:mode])
        docker_env: Environment variables to pass (KEY=VALUE)
        docker_network: Docker network mode
        docker_user: User to run as (UID:GID)
        docker_args: Additional `docker run` arguments (see parse_docker_args)
        dry_run: If True, only print the command
        quiet: If True, suppress stdout
    """
    if runner_config.get("dry_run", False):
        logger.info("DRY RUN: Command would be executed")
        return None

    container: Container | None = None
    try:
        client = docker.client.from_env()
        run_kwargs: dict[str, Any] = {
            "image": runner_config.get("docker_image", "ghcr.io/dbt-labs/dbt-core:latest"),
            "command": commands,
            "detach": True,
            "stdout": True,
            "stderr": True,
            "user": runner_config.get("docker_user") or f"{os.getuid()}:{os.getgid()}",
            "environment": get_docker_env(runner_config),
            "volumes": get_docker_volumes(runner_config),
        }

        platform = runner_config.get("docker_platform")
        if platform:
            run_kwargs["platform"] = platform

        network = runner_config.get("docker_network")
        if network:
            run_kwargs["network_mode"] = network

        # Extra `docker run` arguments are translated last so they can override
        # the values derived from the dedicated flags above.
        extra_kwargs = parse_docker_args(runner_config)
        if "environment" in extra_kwargs:
            run_kwargs["environment"] = {
                **(run_kwargs["environment"] or {}),
                **extra_kwargs.pop("environment"),
            }
        run_kwargs.update(extra_kwargs)

        logger.debug(f"Starting container with: {redact(run_kwargs)}")
        container = cast(Container, client.containers.run(**run_kwargs))

        # Capture all logs as string
        output_logs = []
        for log in container.logs(stream=True):
            decoded = log.decode("utf-8")
            sys.stdout.write(decoded)
            sys.stdout.flush()
            output_logs.append(decoded)

        exit_status = container.wait()
        returncode = exit_status.get("StatusCode", 0)
        stdout = "".join(output_logs)
        if returncode != 0:
            print(stdout)
            sys.exit(1)

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
    finally:
        remove_container(container)

def remove_container(container: Container | None) -> None:
    """Remove a finished container so repeated CI runs don't leak stopped containers."""
    if container is None:
        return
    try:
        container.remove(force=True)
    except Exception as e:
        logger.warning(f"Failed to remove container: {e}")

# Translation of the `docker run` CLI flags supported by --docker-args into the
# keyword arguments understood by the Docker SDK. Flags that take no value map
# to a (kwarg, constant) pair; the rest map to a (kwarg, converter) pair.
DOCKER_ARG_FLAGS: dict[str, tuple[str, Any]] = {
    "--privileged": ("privileged", True),
}

DOCKER_ARG_OPTIONS: dict[str, tuple[str, Any]] = {
    "--memory": ("mem_limit", str),
    "-m": ("mem_limit", str),
    "--cpus": ("nano_cpus", lambda v: int(float(v) * 1_000_000_000)),
    "--shm-size": ("shm_size", str),
    "--workdir": ("working_dir", str),
    "-w": ("working_dir", str),
    "--hostname": ("hostname", str),
    "--platform": ("platform", str),
    "--network": ("network_mode", str),
}

def parse_docker_args(runner_config: RunnerConfig) -> dict[str, Any]:
    """
    Translate the free-form --docker-args string into Docker SDK keyword arguments.

    dbt-ci drives Docker through the SDK rather than the `docker` CLI, so only the
    subset of `docker run` flags listed in DOCKER_ARG_FLAGS/DOCKER_ARG_OPTIONS (plus
    -e/--env and --add-host) can be forwarded. Anything else is reported as ignored
    rather than dropped silently.
    """
    raw = runner_config.get("docker_args") or ""
    if not raw.strip():
        return {}

    kwargs: dict[str, Any] = {}
    environment: dict[str, str] = {}
    extra_hosts: dict[str, str] = {}
    ignored: list[str] = []

    tokens = shlex.split(raw)
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1

        # Support both `--flag value` and `--flag=value` spellings.
        flag, _, inline_value = token.partition("=")
        value: str | None = inline_value if inline_value else None

        if flag in DOCKER_ARG_FLAGS:
            kwarg, constant = DOCKER_ARG_FLAGS[flag]
            kwargs[kwarg] = constant
            continue

        if flag in ("-e", "--env", "--add-host") or flag in DOCKER_ARG_OPTIONS:
            if value is None:
                if index >= len(tokens):
                    ignored.append(token)
                    continue
                value = tokens[index]
                index += 1

            if flag in ("-e", "--env"):
                key, _, env_value = value.partition("=")
                environment[key] = env_value
            elif flag == "--add-host":
                host, _, address = value.partition(":")
                extra_hosts[host] = address
            else:
                kwarg, converter = DOCKER_ARG_OPTIONS[flag]
                try:
                    kwargs[kwarg] = converter(value)
                except (TypeError, ValueError):
                    ignored.append(f"{flag} {value}")
            continue

        ignored.append(token)

    if environment:
        kwargs["environment"] = environment
    if extra_hosts:
        kwargs["extra_hosts"] = extra_hosts
    if ignored:
        logger.warning(
            "Ignoring unsupported --docker-args entries: %s. dbt-ci runs Docker through "
            "the SDK, which supports: %s.",
            " ".join(ignored),
            ", ".join(sorted(set(DOCKER_ARG_FLAGS) | set(DOCKER_ARG_OPTIONS) | {"-e/--env", "--add-host"})),
        )

    return kwargs

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
        # Try to derive from volume mapping — normalize both sides to absolute paths
        # so that relative config values (e.g. "dbt") match expanded volume keys
        # (e.g. "${PWD}/dbt" → "/home/runner/work/repo/dbt").
        dbt_project_host = runner_config.get("dbt_project_dir")
        if dbt_project_host:
            abs_host = get_absolute_path(dbt_project_host)
            for host_mount, container_mount in volume_map.items():
                host_mount_abs = get_absolute_path(host_mount)
                if abs_host.startswith(host_mount_abs):
                    relative_path = abs_host[len(host_mount_abs):].lstrip("/")
                    container_path_map["dbt_project_dir"] = (
                        f"{container_mount}/{relative_path}" if relative_path else container_mount
                    )
                    break
    
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
