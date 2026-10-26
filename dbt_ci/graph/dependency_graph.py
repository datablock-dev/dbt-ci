"""The dependency graph of a dbt manifest, as the commands load it."""

from argparse import Namespace
from typing import Any, cast
from dbt_ci.errors import DbtCiError
from dbt_ci.utilities.cache import CacheManager
from dbt_ci.schema import DBTManifest, DependencyGraph
from dbt_ci.graph.parser import generate_dependency_graph
from dbt_ci.utilities.paths import get_manifest_file, get_reference_manifest_file


class DbtGraph:
    """
    The dependency graph of the target (pull request) or reference (production) manifest.

    During `init` the manifests are read from where dbt and the state download put them;
    every later command reads the copies `init` cached, so they compare the same state.
    """

    def __init__(self, args: Namespace, is_reference: bool = False):
        """Parse the reference manifest if is_reference is set, else the target manifest."""
        self.args = args
        self.is_reference = is_reference

        manifest: DBTManifest | dict[str, Any] | None
        if getattr(args, "command", None) == "init":
            manifest = (
                get_reference_manifest_file(args.reference_state)
                if is_reference
                else get_manifest_file(getattr(args, "dbt_project_dir"))
            )
        else:
            file_name = "reference_manifest.json" if is_reference else "target_manifest.json"
            manifest = CacheManager(args).get_cache(file_name)
            if manifest is None:
                raise DbtCiError(f"No {file_name} found in the cache. Run 'dbt-ci init' first.")

        self.dependency_graph = generate_dependency_graph(cast(DBTManifest, manifest))

    def to_dict(self) -> DependencyGraph:
        """Convert the DependencyGraph instance to a dictionary."""
        return self.dependency_graph
