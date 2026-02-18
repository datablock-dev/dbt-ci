"""Pydantic models for dbt manifest.json structure and CLI arguments."""
from argparse import Namespace
from typing import Callable, Dict, Any, List, Optional, Literal, Set
from pydantic import BaseModel, Field, ConfigDict

type LoggingLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
type Commands = Literal["init", "delete", "migrate", "ephemeral", "run", "finalize"]

class DBTProfile(BaseModel):
    """Structure of a dbt profiles.yml profile."""
    model_config = ConfigDict(
        protected_namespaces=(),
        extra="allow"
    )

    type: str
    method: Optional[str] = None
    project: Optional[str] = None
    dataset: Optional[str] = None
    threads: Optional[int] = None
    timeout_seconds: Optional[int] = None
    retries: Optional[int] = None
    priority: Optional[str] = None
    location: Optional[str] = None
    keyfile: Optional[str] = None
    keyfile_json: Optional[Dict[str, Any]] = None
    schema: Optional[str] = None
    database: Optional[str] = None
    warehouse: Optional[str] = None
    role: Optional[str] = None
    account: Optional[str] = None
    user: Optional[str] = None
    password: Optional[str] = None
    port: Optional[int] = None
    host: Optional[str] = None
    sid: Optional[str] = None
    service: Optional[str] = None
    encrypt: Optional[bool] = None
    trust_cert: Optional[bool] = None
    oauth_access_token: Optional[str] = None

class DBTProfileConfig(BaseModel):
    """Structure of a dbt profiles.yml profile."""
    target: str
    outputs: Dict[str, DBTProfile]

class Quoting(BaseModel):
    """Quoting configuration."""
    database: Optional[bool] = None
    schema: Optional[bool] = None
    identifier: Optional[bool] = None
    column: Optional[bool] = None


class Metadata(BaseModel):
    """Metadata section of dbt manifest."""
    model_config = ConfigDict(protected_namespaces=())
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


class Checksum(BaseModel):
    """Checksum information for a resource."""
    name: str
    checksum: str


class Docs(BaseModel):
    """Documentation configuration."""
    show: bool = True
    node_color: Optional[str] = None


class Contract(BaseModel):
    """Contract configuration."""
    enforced: bool
    alias_types: bool
    checksum: Optional[str] = None


class Config(BaseModel):
    """Configuration for a dbt resource.
    
    Add more adaptor-specific config options as needed.
    """
    model_config = ConfigDict(protected_namespaces=())
    enabled: bool = True
    alias: Optional[str] = None
    schema: Optional[str] = None
    database: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    meta: Dict[str, Any] = Field(default_factory=dict)
    group: Optional[str] = None
    materialized: str = "view"
    incremental_strategy: Optional[str]
    batch_size: Optional[int]
    lookback: Optional[int]
    begin: Optional[str]
    persist_docs: Dict[str, Any] = Field(default_factory=dict)
    post_hook: List[Any] = Field(default_factory=list)
    pre_hook: List[Any] = Field(default_factory=list)
    quoting: Dict[str, Any] = Field(default_factory=dict)
    column_types: Dict[str, Any] = Field(default_factory=dict)
    full_refresh: Optional[bool]
    unique_key: Optional[str]
    on_schema_change: str = "ignore"
    on_configuration_change: str = "apply"
    grants: Dict[str, Any] = Field(default_factory=dict)
    packages: List[Any] = Field(default_factory=list)
    docs: Docs = Field(default_factory=lambda: Docs(show=True, node_color=None))
    contract: Contract = Field(default_factory=lambda: Contract(enforced=False, alias_types=True, checksum=None))
    event_time: Optional[str] = None
    concurrent_batches: Optional[int] = None
    access: str = "protected"
    freshness: Optional[Any]
    # BigQuery-specific config options
    partition_by: Optional[Dict[str, Any]]
    cluster_by: Optional[List[str]]
    # Snowflake-specific config options
    snowflake_warehouse: Optional[str]
    snowflake_role: Optional[str]


class Ref(BaseModel):
    """Reference to another dbt resource."""
    name: str
    package: Optional[str] = None
    version: Optional[str] = None


class DependsOn(BaseModel):
    """Dependencies of a resource."""
    macros: List[str] = Field(default_factory=list)
    nodes: List[str] = Field(default_factory=list)


class Column(BaseModel):
    """Column definition."""
    name: str
    description: str = ""
    data_type: Optional[str] = None
    constraints: Optional[List[Any]] = None
    meta: Dict[str, Any] = Field(default_factory=dict)
    quote: Optional[bool] = None
    tags: List[str] = Field(default_factory=list)

type NodeResourceType = Literal["model", "macro", "source", "seed", "snapshot", "test", "exposure"]

class Node(BaseModel):
    """A node in the dbt DAG (model, test, seed, etc.)."""
    model_config = ConfigDict(protected_namespaces=())
    database: str
    schema: str
    name: str
    resource_type: NodeResourceType
    package_name: str
    path: str
    original_file_path: str
    unique_id: str
    fqn: List[str] = Field(default_factory=list)
    alias: str
    checksum: Checksum
    config: Config = Field(default_factory=Config)
    tags: List[str] = Field(default_factory=list)
    description: str = ""
    columns: Dict[str, Column] = Field(default_factory=dict)
    meta: Dict[str, Any] = Field(default_factory=dict)
    group: Optional[str] = None
    docs: Docs = Field(default_factory=lambda: Docs(show=True, node_color=None))
    patch_path: Optional[str] = None
    build_path: Optional[str] = None
    unrendered_config: Dict[str, Any] = Field(default_factory=dict)
    created_at: float
    relation_name: str
    raw_code: str = ""
    doc_blocks: List[Any] = Field(default_factory=list)
    language: str = "sql"
    refs: List[Ref] = Field(default_factory=list)
    sources: List[Any] = Field(default_factory=list)
    metrics: List[Any] = Field(default_factory=list)
    functions: List[Any] = Field(default_factory=list)
    depends_on: DependsOn = Field(default_factory=DependsOn)
    compiled_path: Optional[str] = None
    compiled: bool = False
    compiled_code: Optional[str] = None
    extra_ctes_injected: bool = False
    extra_ctes: List[Any] = Field(default_factory=list)
    contract: Contract = Field(default_factory=lambda: Contract(enforced=False, alias_types=True, checksum=None))
    access: str = "protected"
    constraints: List[Any] = Field(default_factory=list)
    version: Optional[str] = None
    latest_version: Optional[str] = None
    deprecation_date: Optional[str] = None
    primary_key: List[str] = Field(default_factory=list)
    time_spine: Optional[Any] = None


class Macro(BaseModel):
    """A dbt macro definition."""
    name: str
    unique_id: str
    package_name: str
    path: str
    original_file_path: str
    macro_sql: str
    depends_on: DependsOn = Field(default_factory=DependsOn)
    description: str = ""
    meta: Dict[str, Any] = Field(default_factory=dict)
    docs: Docs = Field(default_factory=lambda: Docs(show=True, node_color=None))
    patch_path: Optional[str] = None
    arguments: List[Any] = Field(default_factory=list)
    created_at: float
    supported_languages: Optional[List[str]] = None


class Source(BaseModel):
    """A dbt source definition."""
    model_config = ConfigDict(protected_namespaces=())
    database: str
    schema: str
    name: str
    resource_type: str
    package_name: str
    path: str
    original_file_path: str
    unique_id: str
    fqn: List[str] = Field(default_factory=list)
    source_name: str
    source_description: str = ""
    loader: str = ""
    identifier: str
    quoting: Quoting = Field(default_factory=Quoting)
    loaded_at_field: Optional[str] = None
    freshness: Optional[Any] = None
    external: Optional[Any] = None
    description: str = ""
    columns: Dict[str, Column] = Field(default_factory=dict)
    meta: Dict[str, Any] = Field(default_factory=dict)
    source_meta: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    config: Config = Field(default_factory=Config)
    patch_path: Optional[str] = None
    unrendered_config: Dict[str, Any] = Field(default_factory=dict)
    relation_name: str
    created_at: float


class DBTManifest(BaseModel):
    """Complete dbt manifest.json structure."""
    model_config = ConfigDict(extra="allow")

    metadata: Metadata
    nodes: Dict[str, Node] = Field(default_factory=dict)
    sources: Dict[str, Source] = Field(default_factory=dict)
    macros: Dict[str, Macro] = Field(default_factory=dict)
    docs: Dict[str, Any] = Field(default_factory=dict)
    exposures: Dict[str, Any] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    groups: Dict[str, Any] = Field(default_factory=dict)
    selectors: Dict[str, Any] = Field(default_factory=dict)
    disabled: Dict[str, Any] = Field(default_factory=dict)
    parent_map: Dict[str, List[str]] = Field(default_factory=dict)
    child_map: Dict[str, List[str]] = Field(default_factory=dict)
    group_map: Dict[str, Any] = Field(default_factory=dict)
    saved_queries: Dict[str, Any] = Field(default_factory=dict)
    semantic_models: Dict[str, Any] = Field(default_factory=dict)
    unit_tests: Dict[str, Any] = Field(default_factory=dict)
    functions: Dict[str, Any] = Field(default_factory=dict)


class CLIArgs(BaseModel):
    """
        Command-line arguments for the DBT CI Tool.
        These args 
    """
    reference_manifest_path: str
    profiles_dir: Optional[str] = None
    dbt_project_dir: str
    target: str
    vars: str = ""
    dry_run: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_file: Optional[str] = None
    mode: Literal["run", "test", "snapshot", "seed", None] = None
    runner: Literal["local", "docker"] = "local"
    docker_image: str = "ghcr.io/dbt-labs/dbt-core:latest"
    docker_platform: Optional[str] = None
    docker_volumes: List[str] = Field(default_factory=list)
    docker_env: List[str] = Field(default_factory=list)
    docker_network: str = "host"
    docker_user: Optional[str] = None
    docker_args: str = ""

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
class DependenciesByType(BaseModel):
    model: Set[str] = Field(default_factory=set)
    macro: Set[str] = Field(default_factory=set)
    source: Set[str] = Field(default_factory=set)
    seed: Set[str] = Field(default_factory=set)
    snapshot: Set[str] = Field(default_factory=set)
    test: Set[str] = Field(default_factory=set)
    exposure: Set[str] = Field(default_factory=set)

class DependencyGraphDownstreamDependency(BaseModel):
    node_dependencies: Set[str] = Field(default_factory=set)
    dependencies_by_type: DependenciesByType = Field(default_factory=DependenciesByType)

type DBTMaterialized = Literal[
    "view",
    "table",
    "incremental",
    "ephemeral",
    "snapshot",
    "test",
    "seed"
]
class DependencyGraphNode(BaseModel):
    """Structured representation of dbt dependencies for lineage analysis."""
    model_config = ConfigDict(protected_namespaces=())
    
    name: str
    id: str
    database: str
    schema: str
    resource_type: DependencyGraphNodeType
    original_file_path: str
    compiled_path: str
    compiled_code: str
    config: Config = Field(default_factory=Config)
    columns: Set[str] = Field(default_factory=set)
    materialized: DBTMaterialized
    incremental_strategy: Optional[str] = None
    downstream_dependencies: DependencyGraphDownstreamDependency = Field(default_factory=DependencyGraphDownstreamDependency)
    upstream_dependencies: DependencyGraphDownstreamDependency = Field(default_factory=DependencyGraphDownstreamDependency)
    indirect_upstream_dependencies: DependencyGraphDownstreamDependency = Field(default_factory=DependencyGraphDownstreamDependency)
    indirect_downstream_dependencies: DependencyGraphDownstreamDependency = Field(default_factory=DependencyGraphDownstreamDependency)

class DependencyGraph(BaseModel):
    """Complete dependency graph for dbt resources."""
    metadata: Metadata
    model: Dict[str, DependencyGraphNode] = Field(default_factory=dict)
    macro: Dict[str, DependencyGraphNode] = Field(default_factory=dict)
    seed: Dict[str, DependencyGraphNode] = Field(default_factory=dict)
    snapshot: Dict[str, DependencyGraphNode] = Field(default_factory=dict)
    source: Dict[str, DependencyGraphNode] = Field(default_factory=dict)
    test: Dict[str, DependencyGraphNode] = Field(default_factory=dict)
    exposure: Dict[str, DependencyGraphNode] = Field(default_factory=dict)

type Runners = Literal["local", "docker", "bash", "dbt"]

class RunnerConfig(BaseModel):
    """Configuration for dbt command execution across different runners."""
    #reference_state: str -> Moved to init command only
    runner: Runners = "dbt"
    dbt_project_dir: str
    profiles_dir: Optional[str] = None
    target: Optional[str] = None
    vars: str = ""
    entrypoint: str = "dbt"
    dry_run: bool = False
    quiet: bool = False
    log_level: LoggingLevel = "INFO"
    dbt_version: Optional[str] = None
    adapter: Optional[str] = None
    # Docker-specific configuration
    docker_image: Optional[str] = None
    docker_platform: Optional[str] = None
    docker_volumes: List[str] = Field(default_factory=list)
    docker_env: List[str] = Field(default_factory=list)
    docker_network: str = "host"
    docker_user: Optional[str] = None
    docker_args: str = ""
    # Bash-specific configuration
    shell_path: str = "/bin/bash"

class OptionsConfig(BaseModel):
    """Configuration mapping for CLI options."""
    env_vars: List[str] = Field(default_factory=list)
    cli_flags: List[str] = Field(default_factory=list)
    required: bool = False
    default: Optional[Any] = None
    help: str = ""
    choices: Optional[List[Any]] = None
    resolve_value: Optional[Callable[..., Any]] = None  # Explore this option for complex value resolution

class NodeConfig(BaseModel):
    """Configuration for a dbt node's database location."""
    model_config = ConfigDict(protected_namespaces=())
    
    database: Optional[str] = None
    schema: Optional[str] = None
    name: Optional[str] = None
    alias: Optional[str] = None

class EphemeralMapNode(BaseModel):
    """Structure for nodes in the ephemeral environment map."""
    name: str
    resource_type: str
    ephemeral_config: Optional[NodeConfig] = None
    reference_config: Optional[NodeConfig] = None

class DeleteMapNode(BaseModel):
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

class ConnectorConfig(BaseModel):
    """Configuration for supported connectors."""
    client: Callable[..., Any]
    ephemeral: Callable[[Dict[str, EphemeralMapNode], Namespace], None]
    delete: Callable[[Dict[str, DeleteMapNode], Namespace], None]
    migration: Callable[..., Any]  # Fix

# Add better type definitions
class MigrationMapNodeEntry(BaseModel):
    """Entry for a node in the migration map."""
    table_id: str
    compiled_code: Optional[str] = None
    old_partitioning: Optional[Any] = None
    new_partitioning: Optional[Any] = None


class MigrationMap(BaseModel):
    """Structure for tracking table partitioning migrations."""
    connector: str
    nodes: Dict[str, MigrationMapNodeEntry] = Field(default_factory=dict)

class StorageConnectorConfig(BaseModel):
    """Configuration for storage connectors."""
    name: str
    client: Callable[..., Any]
    upload: Callable[[str, dict], None]
    download: Callable[[str], DBTManifest]

type SupportedStorageConnectors = Literal["google", "aws"]
type StorageConnector = Dict[SupportedStorageConnectors, StorageConnectorConfig]

MODE_MAPPING: Dict[RunModes, Optional[str]] = {
    "all": None,
    "seeds": "seed",
    "models": "run",
    "tests": "test",
    "snapshots": "snapshot"
}

REVERSE_MODE_MAPPING: Dict[Optional[str], RunModes] = {v: k for k, v in MODE_MAPPING.items()}

NODE_TYPE_COMMAND_MAPPING: Dict[str, DependencyGraphNodeType] = {
    "models": "model",
    "macros": "macro",
    "seeds": "seed",
    "snapshots": "snapshot",
    "tests": "test"
}

MANIFEST_KEY_MAPPING = {
    "model": "nodes",
    "seed": "nodes",
    "snapshot": "nodes",
    "test": "nodes",
    "macro": "macros",
    "exposure": "exposures",
    "source": "sources"
}