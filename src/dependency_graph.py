import json
import os
from typing import Dict, List, Optional
from argparse import Namespace
from src.parser import generate_dependency_graph
from src.paths import get_dbt_project_file, get_manifest_file, get_prod_manifest_file, get_profiles_file
from src.runners import local_runner, docker_runner
from src.schema import DependencyGraph, DependencyGraphNode, DependencyGraphNodeType

class DbtGraph:
    """Structured representation of dbt dependencies for lineage analysis."""
    def __init__(self, args: Namespace):
        self.args = args
        self.runner = args.runner
        self.selector = args.selector
        self.mode = args.mode
        
        # Docker configuration
        self.docker_image = args.docker_image
        self.docker_volumes = getattr(args, 'docker_volumes', [])
        self.docker_env = getattr(args, 'docker_env', [])
        self.docker_network = getattr(args, 'docker_network', 'host')
        self.docker_user = getattr(args, 'docker_user', None)
        self.docker_args = getattr(args, 'docker_args', '')
        
        # Convert paths to absolute paths
        self.dbt_project_dir: str = os.path.abspath(args.dbt_project_dir)
        self.prod_manifest_dir: str = os.path.abspath(args.prod_manifest_dir)
        self.project = get_dbt_project_file(args.dbt_project_dir)
        self.profiles_dir: Optional[str] = os.path.abspath(args.profiles_dir) if args.profiles_dir else None
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
        self.dependency_graph = generate_dependency_graph(args.dbt_project_dir)

    def set_target(self):
        """Set the target from args if provided, otherwise get from profile."""
        if self.args.target and self.args.target != "default":
            return self.args.target
        else:
            return self.get_target_profile()["target_name"]

    def get_state_modified(
        self, 
        node_type: Optional[DependencyGraphNodeType] = None,
        node_ids: Optional[List[str]] = None
    ) -> List[str] | None:
        """Get the state modified for a given node type and/or list of node ids."""
        project_profile = self.project.get("profile", "")
        node_names: List[str] | None = None

        command = [
            "dbt",
            "ls",
            "--select", "state:modified+",
            *(["--target", self.target] if self.target else []),
            *(["--vars", self.vars] if self.vars else []),
            "--state", self.prod_manifest_dir,
            "--project-dir", self.dbt_project_dir,
            *(["--profiles-dir", self.profiles_dir] if self.profiles_dir else [])
        ]

        if self.runner == "local":
            output = local_runner(
                command, 
                dry_run=self.dry_run,
                quiet=True
            )
        elif self.runner == "docker":
            output = docker_runner(
                commands=command,
                dbt_project_dir=self.dbt_project_dir,
                profiles_dir=self.profiles_dir,
                state_dir=self.prod_manifest_dir,
                docker_image=self.docker_image,
                docker_volumes=self.docker_volumes,
                docker_env=self.docker_env,
                docker_network=self.docker_network,
                docker_user=self.docker_user,
                docker_args=self.docker_args,
                dry_run=self.dry_run,
                quiet=True
            )
        else:
            raise ValueError(f"Unknown runner: {self.runner}")

        if output is None:
            print("No modified nodes found.")
            return None

        modified_nodes = {
            line.strip() for line in output.stdout.splitlines()
            if line.startswith(f"{project_profile}.")
        }

        node_names = [nid.split(".")[-1] for nid in modified_nodes]
        return node_names
            

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