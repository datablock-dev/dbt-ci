"""TypedDict definitions for dbt manifest.json structure and CLI arguments."""
from argparse import Namespace
from typing import Callable, Any, Optional, TypedDict, NotRequired, Literal, Set

type LoggingLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
type Commands = Literal["init", "delete", "migrate", "ephemeral", "run", "finalize"]
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
    keyfile_json: Optional[dict[str, Any]]
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
    outputs: dict[str, DBTProfile]

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
    env: dict[str, Any]
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
    tags: list[str]
    meta: dict[str, Any]
    group: Optional[str]
    materialized: str
    incremental_strategy: Optional[str]
    batch_size: Optional[int]
    lookback: Optional[int]
    begin: Optional[str]
    persist_docs: dict[str, Any]
    post_hook: list[Any]
    pre_hook: list[Any]
    quoting: dict[str, Any]
    column_types: dict[str, Any]
    full_refresh: Optional[bool]
    unique_key: Optional[str]
    on_schema_change: str
    on_configuration_change: str
    grants: dict[str, Any]
    packages: list[Any]
    docs: Docs
    contract: Contract
    event_time: Optional[str]
    concurrent_batches: Optional[int]
    access: str
    freshness: Optional[Any]
    # BigQuery-specific config options
    partition_by: Optional[dict[str, Any]]
    cluster_by: Optional[list[str]]
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
    macros: list[str]
    nodes: list[str]


class Column(TypedDict, total=False):
    """Column definition."""
    name: str
    description: str
    data_type: Optional[str]
    constraints: Optional[list[Any]]
    meta: dict[str, Any]
    quote: Optional[bool]
    tags: list[str]

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
    fqn: list[str]
    alias: str
    checksum: Checksum
    config: Config
    tags: list[str]
    description: str
    columns: dict[str, Column]
    meta: dict[str, Any]
    group: Optional[str]
    docs: Docs
    patch_path: Optional[str]
    build_path: Optional[str]
    unrendered_config: dict[str, Any]
    created_at: float
    relation_name: str
    raw_code: str
    doc_blocks: list[Any]
    language: str
    refs: list[Ref]
    sources: list[Any]
    metrics: list[Any]
    functions: list[Any]
    depends_on: DependsOn
    compiled_path: Optional[str]
    compiled: bool
    compiled_code: Optional[str]
    extra_ctes_injected: bool
    extra_ctes: list[Any]
    contract: Contract
    access: str
    constraints: list[Any]
    version: Optional[str]
    latest_version: Optional[str]
    deprecation_date: Optional[str]
    primary_key: list[str]
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
    meta: dict[str, Any]
    docs: Docs
    patch_path: Optional[str]
    arguments: list[Any]
    created_at: float
    supported_languages: Optional[list[str]]


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
    fqn: list[str]
    source_name: str
    source_description: str
    loader: str
    identifier: str
    quoting: Quoting
    loaded_at_field: Optional[str]
    freshness: Optional[Any]
    external: Optional[Any]
    description: str
    columns: dict[str, Column]
    meta: dict[str, Any]
    source_meta: dict[str, Any]
    tags: list[str]
    config: Config
    patch_path: Optional[str]
    unrendered_config: dict[str, Any]
    relation_name: str
    created_at: float


class DBTManifest(TypedDict):
    """Complete dbt manifest.json structure."""
    metadata: Metadata
    nodes: dict[str, Node]
    sources: dict[str, Source]
    macros: dict[str, Macro]
    docs: dict[str, Any]
    exposures: dict[str, Any]
    metrics: dict[str, Any]
    groups: dict[str, Any]
    selectors: dict[str, Any]
    disabled: dict[str, Any]
    parent_map: dict[str, list[str]]
    child_map: dict[str, list[str]]
    group_map: dict[str, Any]
    saved_queries: dict[str, Any]
    semantic_models: dict[str, Any]
    unit_tests: dict[str, Any]
    functions: dict[str, Any]


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
    docker_volumes: list[str]
    docker_env: list[str]
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
    model: dict[str, DependencyGraphNode]
    macro: dict[str, DependencyGraphNode]
    seed: dict[str, DependencyGraphNode]
    snapshot: dict[str, DependencyGraphNode]
    source: dict[str, DependencyGraphNode]
    test: dict[str, DependencyGraphNode]
    exposure: dict[str, DependencyGraphNode]

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
    docker_volumes: list[str]
    docker_env: list[str]
    docker_network: str
    docker_user: Optional[str]
    docker_args: str
    # Bash-specific configuration
    shell_path: str

class OptionsConfig(TypedDict):
    """Configuration mapping for CLI options."""
    env_vars: list[str]
    cli_flags: list[str]
    required: bool
    default: Optional[Any]
    help: str
    choices: Optional[list[Any]]
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

type EphemeralConnectors = dict[
    SupportedConnectorsEphemeralStrategy,
    Callable[[dict[str, EphemeralMapNode], Namespace], None]
]

class ConnectorStrategiesConfig(TypedDict):
    """Configuration for supported connector strategies."""
    ephemeral: Callable[[dict[str, EphemeralMapNode], Namespace], None]
    delete: Callable[[dict[str, DeleteMapNode], Namespace], None]
    migration: Callable[..., Any] # Fix

class ConnectorMethodsConfig(TypedDict):
    """Configuration for supported connector methods."""
    # We need to standardize the return type for query.
    # Ideally, it should return a structured result with success status, error messages, and any relevant metadata.
    query: Callable[[Any, str], None]
    # Dataset methods
    create_datasets: Callable[[Any, set[str], Optional[bool], Optional[int]], None]
    delete_datasets: Callable[[Any, set[str], Optional[bool], Optional[int]], None]
    # Table methods
    create_tables: Callable[[Any, str], None]
    delete_tables: Callable[[Any, str], None]
    # Schema methods?


class ConnectorConfig(TypedDict):
    """Configuration for supported connectors."""
    client: Callable[..., Any]
    strategies: ConnectorStrategiesConfig
    methods: ConnectorMethodsConfig

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
    nodes: dict[str, MigrationMapNodeEntry]

class StorageConnectorConfig(TypedDict):
    """Configuration for storage connectors."""
    name: str
    client: Callable[..., Any]
    upload: Callable[[str, dict], None]
    download: Callable[[str], DBTManifest]

type SupportedStorageConnectors = Literal["google", "aws"]
type StorageConnector = dict[SupportedStorageConnectors, StorageConnectorConfig]

MODE_MAPPING: dict[RunModes, Optional[str]] = {
    "all": None,
    "seeds": "seed",
    "models": "run",
    "tests": "test",
    "snapshots": "snapshot"
}

REVERSE_MODE_MAPPING: dict[Optional[str], RunModes] = {v: k for k, v in MODE_MAPPING.items()}

NODE_TYPE_COMMAND_MAPPING: dict[str, DependencyGraphNodeType] = {
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