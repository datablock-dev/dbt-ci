"""
DbtGraph class for representing dbt dependencies and lineage.
This module defines the DbtGraph class, which encapsulates the dependency graph of dbt resources
"""

import json
from argparse import Namespace
from typing import cast
from dbt_ci.cache import CacheManager
from dbt_ci.schema import DBTManifest, DependencyGraph
from dbt_ci.graph.parser import generate_dependency_graph
from dbt_ci.utilities.paths import get_manifest_file, get_reference_manifest_file

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
    def __init__(self, args: Namespace, is_reference: bool = False):
        cache = CacheManager(args)
        self.args = args
        self.is_reference = is_reference
        for key, value in self.args.__dict__.items():
            setattr(self, key, value)
        
        # Keep paths as provided by user (relative or absolute)
        if getattr(self.args, "command", None) == "init":
            self.dbt_project_dir = self.args.dbt_project_dir
            self.dependency_graph = generate_dependency_graph(
                manifest_file=get_manifest_file(self.dbt_project_dir) if not self.is_reference 
                else get_reference_manifest_file(self.args.reference_state),
            )
        # We retrive manifest file from cache
        # Potential improvements would be to only store the dependency graph in cache
        # to avoid having to read and parse the entire manifest file each time this class is 
        # initialized, which can be costly for large projects.
        else:
            manifest_file = cache.get_cache("target_manifest.json" if not self.is_reference else "reference_manifest.json")
            self.dependency_graph = generate_dependency_graph(cast(DBTManifest, manifest_file))

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
