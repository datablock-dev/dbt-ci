import json
import os
from src.runners import run_dbt_command
from typing import Dict, List, Optional
from argparse import Namespace
from src.parser import generate_dependency_graph
from src.paths import get_dbt_project_file, get_manifest_file, get_prod_manifest_file, get_profiles_file
from src.schema import DependencyGraph, DependencyGraphNode, DependencyGraphNodeType, RunnerConfig

class DbtGraph:
    """
    Structured representation of dbt dependencies for lineage analysis.
    This class encapsulates the dependency graph of dbt resources, providing methods to access and analyze the relationships between models, macros, sources, seeds, snapshots, tests, and exposures. It also includes functionality to determine which nodes have been modified based on the state comparison between the production manifest and the target manifest.
    The DbtGraph class is initialized with the command-line arguments provided by the user, which include paths to the dbt project, production manifest, profiles directory, and other configuration options. It generates the dependency graph using the provided manifest files and allows users to query for modified nodes and their dependencies.

    Args:
        args (Namespace): Command-line arguments parsed
        user_production_state (bool, optional): Flag indicating whether to use the production state for comparison. Defaults to False.

    Returns:
        DbtGraph: An instance of the DbtGraph class containing the dependency graph and related
    """
    def __init__(
        self, 
        args: Namespace,
        user_production_state: bool = False
    ):
        self.args = args
        self.runner = args.runner
        self.selector = args.selector
        self.mode = args.mode
        self.user_production_state = user_production_state
        
        # Docker configuration
        self.docker_image = args.docker_image
        self.docker_platform = getattr(args, 'docker_platform', None)
        self.docker_volumes = getattr(args, 'docker_volumes', [])
        self.docker_env = getattr(args, 'docker_env', [])
        self.docker_network = getattr(args, 'docker_network', 'host')
        self.docker_user = getattr(args, 'docker_user', None)
        self.docker_args = getattr(args, 'docker_args', '')
        
        # Bash runner configuration
        shell_path = getattr(args, 'shell_path', '/bin/bash')
        # Shell path needs to be absolute for subprocess execution
        self.shell_path = os.path.abspath(shell_path) if not os.path.isabs(shell_path) else shell_path
        
        # Keep paths as provided by user (relative or absolute)
        self.dbt_project_dir: str = args.dbt_project_dir
        self.prod_manifest_dir: str = args.prod_manifest_dir
        self.project = get_dbt_project_file(args.dbt_project_dir)
        self.profiles_dir: Optional[str] = args.profiles_dir
        self.profile = get_profiles_file(
            dbt_project_dir=args.dbt_project_dir,
            profiles_dir=args.profiles_dir
        )
        self.reference_manifest_file = get_prod_manifest_file(args.prod_manifest_dir)
        self.prod_manifest_file = self.reference_manifest_file
        self.target_manifest_file = get_manifest_file(args.dbt_project_dir)
        self.target = self.set_target()
        self.vars: str = args.vars
        self.dry_run: bool = args.dry_run
        self.log_level: str = args.log_level
        self.dependency_graph = generate_dependency_graph(
            args.dbt_project_dir if not self.user_production_state else args.prod_manifest_dir,
            is_state_manifest=self.user_production_state
        )

    def set_target(self):
        """Set the target from args if provided, otherwise get from profile."""
        if self.args.target and self.args.target != "default":
            return self.args.target
        else:
            return self.get_target_profile()["target_name"]
    
    def _get_absolute_path(self, path: str) -> str:
        """Convert path to absolute if it's relative."""
        return os.path.abspath(path) if not os.path.isabs(path) else path
    
    def _translate_path_for_container(self, path: str, container_workdir: str = None, host_to_container_base: str = None) -> str:
        """Translate host path to container path for Docker/containerized environments.
        
        Args:
            path: The path to translate
            container_workdir: Working directory set in container (e.g., "/dbt", "/app")
            host_to_container_base: If the host project dir is mounted at a specific location in container
        
        Returns:
            Translated path for use in container
        """
        if not container_workdir and not host_to_container_base:
            # No translation configured, return as-is
            return path
        
        # Get absolute paths for comparison
        abs_path = self._get_absolute_path(path)
        abs_project_dir = self._get_absolute_path(self.dbt_project_dir)
        
        if container_workdir:
            # If path equals the project directory exactly, return current directory
            if abs_path == abs_project_dir:
                return "."
            
            # If path is within the project directory, make it relative to container working dir
            if abs_path.startswith(abs_project_dir + os.sep):
                rel_path = os.path.relpath(abs_path, abs_project_dir)
                return "./" + rel_path.replace(os.sep, '/')
        
        # Otherwise return the path as-is
        return path
    
    def _get_runner_config(self) -> RunnerConfig:
        """Build RunnerConfig from instance properties.
        
        Returns:
            RunnerConfig dict with all runner settings
        """
        
        return RunnerConfig(
            runner=self.runner,
            dbt_project_dir=self.dbt_project_dir,
            prod_manifest_dir=self.prod_manifest_dir,
            profiles_dir=self.profiles_dir,
            target=self.target,
            vars=self.vars,
            entrypoint=self.args.entrypoint,
            dry_run=self.dry_run,
            quiet=False,  # Can be overridden per-call
            docker_image=self.docker_image,
            docker_platform=self.docker_platform,
            docker_volumes=self.docker_volumes,
            docker_env=self.docker_env,
            docker_network=self.docker_network,
            docker_user=self.docker_user,
            docker_args=self.docker_args,
            shell_path=self.shell_path
        )

    def get_state_modified(
        self, 
        selector: str = "state:modified+",
        node_type: Optional[DependencyGraphNodeType] = None,
        node_ids: Optional[List[str]] = None
    ) -> List[str] | None:
        """Get modified nodes based on state comparison.
        
        Args:
            selector: dbt selector syntax (default: "state:modified+")
            node_type: Optional filter by node type (not yet implemented)
            node_ids: Optional filter by specific node IDs (not yet implemented)
        
        Returns:
            List of modified node names, or None if no changes
        """
        
        # Build dbt ls command arguments
        command_args = [
            "ls",
            "--select", selector,
            *(["--target", self.target] if self.target else []),
            *(["--vars", self.vars] if self.vars else []),
            "--state", self.prod_manifest_dir,
            "--project-dir", self.dbt_project_dir,
            *(["--profiles-dir", self.profiles_dir] if self.profiles_dir else [])
        ]
        
        # Run command through dispatcher
        output = run_dbt_command(
            command_args=command_args,
            runner_config=self._get_runner_config(),
            quiet=True
        )
        
        if output is None:
            print("No modified nodes found.")
            return None
        
        # Parse output to extract node names
        project_profile = self.project.get("profile", "")
        modified_nodes = {
            line.strip() for line in output.stdout.splitlines()
            if line.startswith(f"{project_profile}.")
        }
        
        node_names = [nid.split(".")[-1] for nid in modified_nodes]
        return node_names if node_names else None

            

    def get_node(self, node_id: str) -> Dict[str, DependencyGraphNode] | None:
        match = None
        for node_type in self.dependency_graph.keys():
            if node_type == "metadata":
                continue

            if node_id in self.dependency_graph[node_type]:
                match = self.dependency_graph[node_type][node_id]
                break
        
        return match
            
    def get_nodes(self, node_ids: List[str]) -> Dict[str, Dict[str, DependencyGraphNode]] | None:
        nodes = {}
        for node_type in self.dependency_graph.keys():
            if node_type == "metadata":
                continue

            for node_id in node_ids:
                if node_id in self.dependency_graph[node_type]:
                    nodes[node_id] = self.dependency_graph[node_type][node_id]
        if len(nodes.keys()) == 0:
            return None
        
        return nodes
    
    def get_target_profile(self) -> Dict:
        """Get the default profile from the profiles.yml file."""
        profile = self.project.get("profile", "")
        outputs = self.profile.get(profile, {}).get("outputs", {})
        target = self.profile.get(profile, {}).get("target", "")

        return {
            "config": outputs.get(target, {}),
            "target_name": target
        }

    def to_dict(self) -> DependencyGraph:
        """Convert the DependencyGraph instance to a dictionary."""
        return self.dependency_graph
    
    def to_json(self, destination_path: str = "./dependency_graph.json") -> None:
        """Convert the DependencyGraph instance to a JSON string."""
        with open(destination_path, 'w', encoding='utf-8') as file:
            json.dump(
                obj=self.dependency_graph, 
                fp=file, 
                indent=4, 
                default=lambda o: list(o) if isinstance(o, set) else o
            )