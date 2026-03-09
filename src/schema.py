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

type DbtNode = Node | Macro | Source

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
    query: Callable[[Any, str], str | None]
    # Dataset methods
    create_datasets: Callable[[Any, set[str], bool, int], None]
    delete_datasets: Callable[[Any, set[str], bool, int], None]
    # Table methods
    create_tables: Callable[[Any, set[str], bool, int], None]
    delete_tables: Callable[[Any, set[str], bool, int], None]


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

###################################################################
#                    Dbt CI State Schemas                         #
###################################################################

# Nodes grouped by resource_type, then keyed by node_id.
# e.g. {"model": {"model.pkg.foo": DependencyGraphNode}, "snapshot": {...}}
type StructuredNodes = dict[str, dict[str, DependencyGraphNode]]

class StateChangeSummary(TypedDict):
    """Top-level cache structure written by the init command."""
    modified_nodes: StructuredNodes | None
    deleted_nodes: StructuredNodes | None
    new_nodes: StructuredNodes | None

class DbtCompileOptions(TypedDict):
    target: str | None
    vars: str | None

class DbtCiConfig(TypedDict):
    """Configuration for the DBT CI Tool, including CLI arguments and connector configurations."""
    connector: SupportedConnectors
    reference: DbtCompileOptions
    target: DbtCompileOptions

class DbtCiManifest(TypedDict):
    """Structure of the cache.json files written to storage by the reference and target states."""
    config: DbtCiConfig
    modified_nodes: StructuredNodes | None
    deleted_nodes: StructuredNodes | None
    new_nodes: StructuredNodes | None

###################################################################
#                   GitHub Actions Schemas                        #
###################################################################

class GitHubContext(TypedDict):
    """
    Typed representation of the GitHub Actions `github` context object.

    This context is available throughout any job or step in a workflow run.
    Fields marked NotRequired are only populated for specific event types
    or execution contexts (e.g. pull_request, composite actions, re-runs).

    Reference: https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/accessing-contextual-information-about-workflow-runs#github-context
    """
    # The GitHub Actions token for the current workflow run.
    token: str
    # The job_id of the current job (only set during job execution steps).
    job: str
    # The fully-formed ref that triggered the workflow run (e.g. refs/heads/main).
    ref: str
    # The commit SHA that triggered the workflow run.
    sha: str
    # The owner and repository name (e.g. octocat/hello-world).
    repository: str
    # The repository owner's username.
    repository_owner: str
    # The repository owner's account ID (numeric string).
    repository_owner_id: str
    # The ID of the repository (numeric string).
    repository_id: str
    # The Git URL to the repository (e.g. git://github.com/octocat/hello-world.git).
    repositoryUrl: str
    # A unique number for each workflow run within a repository (does not change on re-run).
    run_id: str
    # A unique number for each run of a particular workflow; increments with each new run.
    run_number: str
    # A unique number for each attempt of a particular workflow run; increments on re-run.
    run_attempt: str
    # Number of days that workflow run logs and artifacts are retained.
    retention_days: str
    # Username of the user that triggered the initial workflow run.
    actor: str
    # Account ID of the person or app that triggered the initial workflow run.
    actor_id: str
    # Username of the user that initiated the re-run (may differ from actor on re-runs).
    triggering_actor: str
    # The name of the event that triggered the workflow run (e.g. push, pull_request).
    event_name: str
    # The full event webhook payload object.
    event: dict[str, Any]
    # Path on the runner to the file containing the full event webhook payload.
    event_path: str
    # The name of the workflow (or the full path if no name is specified).
    workflow: str
    # The ref path to the workflow file (e.g. octocat/hello-world/.github/workflows/ci.yml@refs/heads/main).
    workflow_ref: str
    # The commit SHA for the workflow file itself.
    workflow_sha: str
    # The name of the action currently running, or the step id for script steps.
    action: str
    # The short ref name of the branch or tag that triggered the run (e.g. main or v1.0.0).
    ref_name: str
    # The type of ref that triggered the run: "branch" or "tag".
    ref_type: Literal["branch", "tag"]
    # True if branch protections or rulesets are configured for the triggering ref.
    ref_protected: bool
    # The source of any secret used in the workflow: None, Actions, Codespaces, or Dependabot.
    secret_source: Literal["None", "Actions", "Codespaces", "Dependabot"]
    # The URL of the GitHub server (e.g. https://github.com).
    server_url: str
    # The URL of the GitHub REST API (e.g. https://api.github.com).
    api_url: str
    # The URL of the GitHub GraphQL API (e.g. https://api.github.com/graphql).
    graphql_url: str
    # Path on the runner to the file that sets environment variables from workflow commands.
    env: str
    # Path on the runner to the file that sets system PATH variables from workflow commands.
    path: str
    # The default working directory on the runner for steps.
    workspace: str

    # --- Fields only available in specific contexts ---

    # The path where the current action is located (composite actions only).
    action_path: NotRequired[str]
    # The ref of the action being executed (e.g. v2); not available in run steps.
    action_ref: NotRequired[str]
    # The owner and repo name of the action being executed (e.g. actions/checkout); not available in run steps.
    action_repository: NotRequired[str]
    # The current result of a composite action step.
    action_status: NotRequired[str]
    # The head_ref (source branch) of the pull request; only set for pull_request / pull_request_target events.
    head_ref: NotRequired[str]
    # The base_ref (target branch) of the pull request; only set for pull_request / pull_request_target events.
    base_ref: NotRequired[str]