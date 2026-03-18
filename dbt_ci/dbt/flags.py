from argparse import Namespace
from typing import Literal, cast

from dbt_ci.utilities.cache import CacheManager
from dbt_ci.schema import DbtCiManifest, DependencyGraphNodeType

dependency_graph_node_type: list[DependencyGraphNodeType] = [
    "model", 
    "macro", 
    "source", 
    "seed", 
    "snapshot", 
    "test", 
    "exposure"
]

def exclude_flag(include: list[DependencyGraphNodeType] | None) -> list[str]:
    """Generate a list of node types to exclude based on the include list."""
    default_list = {
        "model": "--exclude resource_type:model", 
        "macro": "--exclude resource_type:macro", 
        "source": "--exclude resource_type:source", 
        "seed": "--exclude resource_type:seed", 
        "snapshot": "--exclude resource_type:snapshot", 
        "test": "--exclude resource_type:test", 
        "exposure": "--exclude resource_type:exposure"
    }


    exclude_flags: set[str] = set()

    if include is None:
        exclude_flags = set(default_list.values())
    else:
        for node_type in dependency_graph_node_type:
            if node_type not in include:
                exclude_flags.add(default_list[node_type])
    
    return list(exclude_flags)

def get_target(args: Namespace, target: Literal["target", "reference_target"]) -> str | None:
    """Get the target from the Namespace, checking both 'target' and 'reference_target' keys."""
    cache = CacheManager(args)
    cache_manifest = cast(DbtCiManifest, cache.get_cache())
    
    cache_target = cache_manifest.get("config", {}).get(target, {}).get("target", None)
    return getattr(args, target, cache_target)

def get_vars(args: Namespace, target: Literal["vars", "reference_vars"]) -> dict | None:
    """Get the vars from the Namespace, checking both 'vars' and 'reference_vars' keys."""
    cache = CacheManager(args)
    cache_manifest = cast(DbtCiManifest, cache.get_cache())
    
    cache_vars = cache_manifest.get("config", {}).get(target, {}).get("vars", None)
    return getattr(args, target, cache_vars)