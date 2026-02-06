"""TypedDict definitions for dbt manifest.json structure and CLI arguments."""
from typing import Dict, Any, List, Optional, TypedDict, NotRequired, Literal, Set


class Quoting(TypedDict):
    """Quoting configuration."""
    database: Optional[bool]
    schema: Optional[bool]
    identifier: Optional[bool]
    column: Optional[bool]


class Metadata(TypedDict):
    """Metadata section of dbt manifest."""
    dbt_schema_version: str
    dbt_version: str
    generated_at: str
    invocation_id: str
    invocation_started_at: str
    env: Dict[str, Any]
    project_name: str
    project_id: str
    user_id: str
    send_anonymous_usage_stats: bool
    adapter_type: str
    quoting: Quoting
    run_started_at: str


class Checksum(TypedDict):
    """Checksum information for a resource."""
    name: str
    checksum: str


class Docs(TypedDict):
    """Documentation configuration."""
    show: bool
    node_color: Optional[str]


class Contract(TypedDict):
    """Contract configuration."""
    enforced: bool
    alias_types: bool
    checksum: NotRequired[Optional[str]]


class Config(TypedDict, total=False):
    """Configuration for a dbt resource."""
    enabled: bool
    alias: Optional[str]
    schema: Optional[str]
    database: Optional[str]
    tags: List[str]
    meta: Dict[str, Any]
    group: Optional[str]
    materialized: str
    incremental_strategy: Optional[str]
    batch_size: Optional[int]
    lookback: Optional[int]
    begin: Optional[str]
    persist_docs: Dict[str, Any]
    post_hook: List[Any]
    pre_hook: List[Any]
    quoting: Dict[str, Any]
    column_types: Dict[str, Any]
    full_refresh: Optional[bool]
    unique_key: Optional[str]
    on_schema_change: str
    on_configuration_change: str
    grants: Dict[str, Any]
    packages: List[Any]
    docs: Docs
    contract: Contract
    event_time: Optional[str]
    concurrent_batches: Optional[int]
    access: str
    freshness: Optional[Any]


class Ref(TypedDict):
    """Reference to another dbt resource."""
    name: str
    package: Optional[str]
    version: Optional[str]


class DependsOn(TypedDict):
    """Dependencies of a resource."""
    macros: List[str]
    nodes: List[str]


class Column(TypedDict, total=False):
    """Column definition."""
    name: str
    description: str
    data_type: Optional[str]
    constraints: Optional[List[Any]]
    meta: Dict[str, Any]
    quote: Optional[bool]
    tags: List[str]


class Node(TypedDict, total=False):
    """A node in the dbt DAG (model, test, seed, etc.)."""
    database: str
    schema: str
    name: str
    resource_type: str
    package_name: str
    path: str
    original_file_path: str
    unique_id: str
    fqn: List[str]
    alias: str
    checksum: Checksum
    config: Config
    tags: List[str]
    description: str
    columns: Dict[str, Column]
    meta: Dict[str, Any]
    group: Optional[str]
    docs: Docs
    patch_path: Optional[str]
    build_path: Optional[str]
    unrendered_config: Dict[str, Any]
    created_at: float
    relation_name: str
    raw_code: str
    doc_blocks: List[Any]
    language: str
    refs: List[Ref]
    sources: List[Any]
    metrics: List[Any]
    functions: List[Any]
    depends_on: DependsOn
    compiled_path: Optional[str]
    compiled: bool
    compiled_code: Optional[str]
    extra_ctes_injected: bool
    extra_ctes: List[Any]
    contract: Contract
    access: str
    constraints: List[Any]
    version: Optional[str]
    latest_version: Optional[str]
    deprecation_date: Optional[str]
    primary_key: List[str]
    time_spine: Optional[Any]


class Macro(TypedDict, total=False):
    """A dbt macro definition."""
    name: str
    unique_id: str
    package_name: str
    path: str
    original_file_path: str
    macro_sql: str
    depends_on: DependsOn
    description: str
    meta: Dict[str, Any]
    docs: Docs
    patch_path: Optional[str]
    arguments: List[Any]
    created_at: float
    supported_languages: Optional[List[str]]


class Source(TypedDict, total=False):
    """A dbt source definition."""
    database: str
    schema: str
    name: str
    resource_type: str
    package_name: str
    path: str
    original_file_path: str
    unique_id: str
    fqn: List[str]
    source_name: str
    source_description: str
    loader: str
    identifier: str
    quoting: Quoting
    loaded_at_field: Optional[str]
    freshness: Optional[Any]
    external: Optional[Any]
    description: str
    columns: Dict[str, Column]
    meta: Dict[str, Any]
    source_meta: Dict[str, Any]
    tags: List[str]
    config: Config
    patch_path: Optional[str]
    unrendered_config: Dict[str, Any]
    relation_name: str
    created_at: float


class DBTManifest(TypedDict):
    """Complete dbt manifest.json structure."""
    metadata: Metadata
    nodes: Dict[str, Node]
    sources: Dict[str, Source]
    macros: Dict[str, Macro]
    docs: Dict[str, Any]
    exposures: Dict[str, Any]
    metrics: Dict[str, Any]
    groups: Dict[str, Any]
    selectors: Dict[str, Any]
    disabled: Dict[str, Any]
    parent_map: Dict[str, List[str]]
    child_map: Dict[str, List[str]]
    group_map: Dict[str, Any]
    saved_queries: Dict[str, Any]
    semantic_models: Dict[str, Any]
    unit_tests: Dict[str, Any]
    functions: Dict[str, Any]


class CLIArgs(TypedDict):
    """Command-line arguments for the DBT CI Tool."""
    prod_manifest_path: str
    profiles_dir: Optional[str]
    dbt_project_dir: str
    target: str
    vars: str
    dry_run: bool
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    log_file: Optional[str]
    mode: Literal["run", "test", "snapshot", "seed", None]
    runner: Literal["local", "docker"]

###########################################
#   Dependency graph structures for lineage analysis
###########################################
type DependencyGraphNodeType = Literal[
    "model", 
    "macro", 
    "source", 
    "seed", 
    "snapshot", 
    "test", 
    "exposure"
]
class DependenciesByType(TypedDict):
    model: Set[str]
    macro: Set[str]
    source: Set[str]
    seed: Set[str]
    snapshot: Set[str]
    test: Set[str]
    exposure: Set[str]
class DependencyGraphDownstreamDependency(TypedDict):
    node_dependencies: Set[str]
    dependencies_by_type: DependenciesByType

class DependencyGraphNode(TypedDict):
    """Structured representation of dbt dependencies for lineage analysis."""
    name: str
    id: str
    database: str
    schema: str
    resource_type: DependencyGraphNodeType
    original_file_path: str
    compiled_path: str
    compiled_code: str
    columns: Set[str]
    downstream_dependencies: DependencyGraphDownstreamDependency
    upstream_dependencies: DependencyGraphDownstreamDependency
    indirect_upstream_dependencies: DependencyGraphDownstreamDependency
    indirect_downstream_dependencies: DependencyGraphDownstreamDependency

class DependencyGraph(TypedDict):
    """Complete dependency graph for dbt resources."""
    metadata: Metadata
    model: Dict[str, DependencyGraphNode]
    macro: Dict[str, DependencyGraphNode]
    seed: Dict[str, DependencyGraphNode]
    snapshot: Dict[str, DependencyGraphNode]
    source: Dict[str, DependencyGraphNode]
    test: Dict[str, DependencyGraphNode]
    exposure: Dict[str, DependencyGraphNode]