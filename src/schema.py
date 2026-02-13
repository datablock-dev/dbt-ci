"""TypedDict definitions for dbt manifest.json structure and CLI arguments."""
from argparse import Namespace
from typing import Callable, Dict, Any, List, Optional, TypedDict, NotRequired, Literal, Set

type LoggingLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
class DBTProfile(TypedDict):
    """Structure of a dbt profiles.yml profile."""
    type: str
    method: Optional[str]
    project: Optional[str]
    dataset: Optional[str]
    threads: Optional[int]
    timeout_seconds: Optional[int]
    retries: Optional[int]
    priority: Optional[str]
    location: Optional[str]
    keyfile: Optional[str]
    keyfile_json: Optional[Dict[str, Any]]
    schema: Optional[str]
    database: Optional[str]
    warehouse: Optional[str]
    role: Optional[str]
    account: Optional[str]
    user: Optional[str]
    password: Optional[str]
    port: Optional[int]
    host: Optional[str]
    sid: Optional[str]
    service: Optional[str]
    encrypt: Optional[bool]
    trust_cert: Optional[bool]
    oauth_access_token: Optional[str]

class DBTProfileConfig(TypedDict):
    """Structure of a dbt profiles.yml profile."""
    target: str
    outputs: Dict[str, DBTProfile]

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
    """
        Add more adaptor-specific config options as needed.
    """
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
    # BigQuery-specific config options
    partition_by: Optional[Dict[str, Any]]
    cluster_by: Optional[List[str]]
    # Snowflake-specific config options
    snowflake_warehouse: Optional[str]
    snowflake_role: Optional[str]


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

type NodeResourceType = Literal["model", "macro", "source", "seed", "snapshot", "test", "exposure"]

class Node(TypedDict, total=False):
    """A node in the dbt DAG (model, test, seed, etc.)."""
    database: str
    schema: str
    name: str
    resource_type: NodeResourceType
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
    reference_manifest_path: str
    profiles_dir: Optional[str]
    dbt_project_dir: str
    target: str
    vars: str
    dry_run: bool
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    log_file: Optional[str]
    mode: Literal["run", "test", "snapshot", "seed", None]
    runner: Literal["local", "docker"]
    docker_image: str
    docker_platform: Optional[str]
    docker_volumes: List[str]
    docker_env: List[str]
    docker_network: str
    docker_user: Optional[str]
    docker_args: str

###########################################
#   Dependency graph structures for lineage analysis
###########################################
type RunModes = Literal[
    "all",
    "seeds",
    "models",
    "tests",
    "snapshots"
]

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

type DBTMaterialized = Literal[
    "view",
    "table",
    "incremental",
    "ephemeral",
    "snapshot",
    "test",
    "seed"
]
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
    config: Config
    columns: Set[str]
    materialized: DBTMaterialized
    incremental_strategy: Optional[str]
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

type Runners = Literal["local", "docker", "bash", "dbt"]

class RunnerConfig(TypedDict):
    """Configuration for dbt command execution across different runners."""
    runner: Runners
    dbt_project_dir: str
    reference_state: str
    profiles_dir: Optional[str]
    target: Optional[str]
    vars: str
    entrypoint: str
    dry_run: bool
    quiet: bool
    log_level: LoggingLevel
    # Docker-specific configuration
    docker_image: Optional[str]
    docker_platform: Optional[str]
    docker_volumes: List[str]
    docker_env: List[str]
    docker_network: str
    docker_user: Optional[str]
    docker_args: str
    # Bash-specific configuration
    shell_path: str

class OptionsConfig(TypedDict):
    """Configuration mapping for CLI options."""
    env_vars: List[str]
    cli_flags: List[str]
    required: bool
    default: Optional[Any]
    help: str
    choices: Optional[List[Any]]
    resolve_value: Optional[Callable[..., Any]] # Explore this option for complex value resolution

class NodeConfig(TypedDict):
    """Configuration for a dbt node's database location."""
    database: Optional[str]
    schema: Optional[str]
    name: Optional[str]
    alias: Optional[str]

class EphemeralMapNode(TypedDict):
    """Structure for nodes in the ephemeral environment map."""
    name: str
    resource_type: str
    ephemeral_config: NodeConfig | None
    reference_config: NodeConfig | None

class DeleteMapNode(TypedDict):
    """Structure for nodes in the delete map."""
    type: NodeResourceType
    name: str
    table_id: str

type SupportedConnectors = Literal[
    "bigquery"
]
type SupportedConnectorsEphemeralStrategy = Literal[
    "bigquery"
]

type EphemeralConnectors = Dict[
    SupportedConnectorsEphemeralStrategy,
    Callable[[Dict[str, EphemeralMapNode], Namespace], None]
]

class ConnectorConfig(TypedDict):
    """Configuration for supported connectors."""
    client: Callable[..., Any]
    ephemeral: Callable[[Dict[str, EphemeralMapNode], Namespace], None]
    delete: Callable[[Dict[str, DeleteMapNode], Namespace], None]
    migration: Callable[..., Any] # Fix

# Add better type definitions
class MigrationMapNodeEntry(TypedDict):
    """Entry for a node in the migration map."""
    table_id: str
    compiled_code: str | None
    old_partitioning: Any | None
    new_partitioning: Any | None


class MigrationMap(TypedDict):
    """Structure for tracking table partitioning migrations."""
    connector: str
    nodes: Dict[str, MigrationMapNodeEntry]

class StorageConnectorConfig(TypedDict):
    """Configuration for storage connectors."""
    client: Callable[..., Any]
    upload: Callable[[str, dict], None]
    download: Callable[[str], DBTManifest]

type SupportedStorageConnectors = Literal["google", "aws"]
type StorageConnector = Dict[SupportedStorageConnectors, StorageConnectorConfig]