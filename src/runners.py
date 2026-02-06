import os
import subprocess
from subprocess import CompletedProcess
from typing import List

def local_runner(
    commands: List[str], 
    dry_run: bool = False,
    quiet: bool = False
) -> CompletedProcess | None:
    """Execute dbt commands locally."""
    if not quiet:
        print(f"Running command: {' '.join(commands)}")
    
    if dry_run:
        print("DRY RUN: Command would be executed")
        return None
    
    try:
        result = subprocess.run(
            commands, 
            check=True, 
            capture_output=True, 
            text=True
        )

        if not quiet:
            print(result.stdout)

        return result
    except subprocess.CalledProcessError as e:
        if e.stderr:
            print(e.stderr)
        if e.stdout:
            print(e.stdout)
        raise

def docker_runner(
    commands: List[str],
    dbt_project_dir: str,
    profiles_dir: str | None,
    state_dir: str,
    docker_image: str,
    docker_platform: str | None = None,
    docker_volumes: List[str] | None = None,
    docker_env: List[str] | None = None,
    docker_network: str = "host",
    docker_user: str | None = None,
    docker_args: str = "",
    dry_run: bool = False,
    quiet: bool = False
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
    
    docker_volumes = docker_volumes or []
    docker_env = docker_env or []
    
    # Auto-detect user if not specified
    if docker_user is None:
        docker_user = f"{os.getuid()}:{os.getgid()}"
    
    # Container paths
    container_project_dir = "/usr/app"
    container_profiles_dir = "/root/.dbt"
    container_state_dir = "/state"
    
    # Build Docker command
    docker_cmd = ["docker", "run"]
    
    # Add platform if specified (useful for Apple Silicon Macs)
    if docker_platform:
        docker_cmd.extend(["--platform", docker_platform])
    
    # Add profiles directory mount if specified
    if profiles_dir:
        docker_cmd.extend(["-v", f"{profiles_dir}:{container_profiles_dir}"])
        docker_cmd.extend(["-e", f"DBT_PROFILES_DIR={container_profiles_dir}"])
    
    # Add network mode
    #docker_cmd.extend(["--network", docker_network])
    
    # Add user
    #docker_cmd.extend(["--user", docker_user])
    
    # Add additional volumes
    for volume in docker_volumes:
        docker_cmd.extend(["-v", volume])
    
    # Add environment variables
    for env in docker_env:
        docker_cmd.extend(["-e", env])
    
    # Add additional docker args
    if docker_args:
        docker_cmd.extend(docker_args.split())
    
    # Add the Docker image
    docker_cmd.append(docker_image)
    
    # Translate dbt command paths to container paths
    translated_commands = []
    for cmd_part in commands:
        # Replace host paths with container paths in dbt command
        if cmd_part == dbt_project_dir:
            translated_commands.append(container_project_dir)
        elif cmd_part == state_dir:
            translated_commands.append(container_state_dir)
        elif profiles_dir and cmd_part == profiles_dir:
            translated_commands.append(container_profiles_dir)
        else:
            translated_commands.append(cmd_part)
    
    # Add the dbt command
    docker_cmd.extend(translated_commands)
    
    if dry_run:
        print("DRY RUN: Command would be executed")
        return None
    
    try:
        result = subprocess.run(
            docker_cmd,
            check=True,
            capture_output=True,
            text=True
        )
        
        if not quiet:
            print(result.stdout)
        
        return result
    except subprocess.CalledProcessError as e:
        if e.stderr:
            print(e.stderr)
        if e.stdout:
            print(e.stdout)
        raise