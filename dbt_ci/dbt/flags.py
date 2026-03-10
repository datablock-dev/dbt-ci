from dbt_ci.schema import DependencyGraphNodeType

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