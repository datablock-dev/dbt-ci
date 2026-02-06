import json
from typing import Dict, List, Optional
from argparse import Namespace
from src.parser import generate_dependency_graph
from src.paths import get_manifest_file
from src.schema import DependencyGraph, DependencyGraphNode, DependencyGraphNodeType

class DbtGraph:
    """Structured representation of dbt dependencies for lineage analysis."""
    def __init__(self, args: Namespace):
        self.dbt_project_dir: str = args.dbt_project_dir
        self.profiles_dir: Optional[str] = args.profiles_dir
        self.reference_manifest_file = get_manifest_file(args.prod_manifest_path)
        self.prod_manifest_file = self.reference_manifest_file
        self.target_manifest_file = get_manifest_file(args.dbt_project_dir)
        self.target: str = args.target
        self.vars: str = args.vars
        self.dry_run: bool = args.dry_run
        self.log_level: str = args.log_level

        self.dependency_graph = generate_dependency_graph(args.prod_manifest_path)

    def get_state_mofidied(
        self, 
        node_type: Optional[DependencyGraphNodeType] = None,
        node_ids: Optional[List[str]] = None
    ):
        """Get the state modified for a given node type and/or list of node ids."""
        

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