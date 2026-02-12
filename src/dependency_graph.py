"""
DbtGraph class for representing dbt dependencies and lineage.
This module defines the DbtGraph class, which encapsulates the dependency graph of dbt resources
"""

import json
import os
from argparse import Namespace
from src.parser import generate_dependency_graph
from src.schema import DependencyGraph
from src.variables import Variables

class DbtGraph:
    """
    Structured representation of dbt dependencies for lineage analysis.
    This class encapsulates the dependency graph of dbt resources, providing methods to access and analyze the relationships between models, macros, sources, seeds, snapshots, tests, and exposures. It also includes functionality to determine which nodes have been modified based on the state comparison between the production manifest and the target manifest.
    The DbtGraph class is initialized with the command-line arguments provided by the user, which include paths to the dbt project, production manifest, profiles directory, and other configuration options. It generates the dependency graph using the provided manifest files and allows users to query for modified nodes and their dependencies.

    Args:
        args (Namespace): Command-line arguments parsed
        is_production (bool, optional): Flag indicating whether to use the production state for comparison. Defaults to False.

    Returns:
        DbtGraph: An instance of the DbtGraph class containing the dependency graph and related
    """
    def __init__(self, args: Namespace, is_production: bool = False):
        self.args = args
        self.variables = Variables(args).to_namespace()
        for key, value in self.variables.__dict__.items():
            setattr(self, key, value)

        self.is_production = is_production

        # Bash runner configuration
        shell_path = getattr(self.variables, 'shell_path', '/bin/bash')
        # Shell path needs to be absolute for subprocess execution
        if not os.path.isabs(shell_path):
            shell_path = os.path.abspath(shell_path)
        
        self.shell_path = shell_path
        
        # Keep paths as provided by user (relative or absolute)
        #self.reference_manifest_file = self.reference_manifest_file
        self.dependency_graph = generate_dependency_graph(
            self.variables.dbt_project_dir if not self.is_production else self.variables.reference_state,
            is_state_manifest=self.is_production
        )

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
