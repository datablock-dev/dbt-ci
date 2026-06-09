# dbt-ci

A CI tool for dbt (data build tool) projects that intelligently runs only modified models based on state comparison, supporting multiple execution environments including local, Docker, and dbt runners.

## How It Works

dbt-ci uses a **cache-based workflow**:

1. **`init`** - Downloads reference state from cloud storage (or uses local), compares with current code, and creates a cache of changes
2. **`run/delete/ephemeral`** - Use the cached state automatically (no need to re-specify state paths)

This design ensures:
- ✅ **Consistent state** across all commands in a CI run
- ✅ **Better performance** (no redundant state downloads)
- ✅ **Simpler CLI** (specify state once in init, reuse everywhere)

## Installation

### From PyPI (Recommended)

```bash
pip install dbt-ci
```

### From GitHub

```bash
# Install from main branch
pip install git+https://github.com/datablock-dev/dbt-ci.git@main

# Install a specific version
pip install git+https://github.com/datablock-dev/dbt-ci.git@v1.0.0
```

### Local Development

```bash
git clone https://github.com/datablock-dev/dbt-ci.git
cd dbt-ci
pip install -e ".[dev]"
```

After installation, the tool is available as `dbt-ci`.

## Quick Start

**The Workflow:** Initialize once with `init`, then run commands that use the cached state.

### 1. Initialize State

First, initialize the dbt-ci state. This downloads/reads reference state and creates a cache:

```bash
dbt-ci init \
  --dbt-project-dir dbt \
  --profiles-dir dbt \
  --reference-target production \
  --state dbt/.dbtstate
```

**With Cloud Storage (GCS/S3):**
```bash
dbt-ci init \
  --dbt-project-dir dbt \
  --state-uri gs://my-bucket/dbt-state/manifest.json \
  --reference-target production \
  --state dbt/.dbtstate
```

### 2. Run Modified Models

After initialization, run commands use the cached state automatically:

```bash
# No need to specify --state again!
dbt-ci run \
  --dbt-project-dir dbt \
  --profiles-dir dbt
```

**With Docker:**
```bash
dbt-ci run \
  --runner docker \
  --docker-image ghcr.io/dbt-labs/dbt-bigquery:latest
```

## Commands

All commands share a set of **common options** (listed in the [Common Options](#common-options) section below). Command-specific flags are listed under each command.

---

### `init` - Initialize State

Creates initial state from your dbt project. **Always run this first.** Downloads reference manifest from cloud storage (if specified) and creates a local cache for subsequent commands.

```bash
dbt-ci init \
  --dbt-project-dir dbt \
  --profiles-dir dbt \
  --state-uri gs://my-bucket/manifest.json \
  --reference-target production \
  --state dbt/.dbtstate
```

**Flags:**

| Flag | Aliases | Env Var(s) | Default | Description |
|------|---------|-----------|---------|-------------|
| `--reference-target` | `--ref-target` | `DBT_REFERENCE_TARGET` | `None` | dbt target for the production/reference manifest |
| `--reference-vars` | `--ref-vars` | `DBT_REFERENCE_VARS` | `None` | Variables to pass to dbt when compiling the reference manifest (YAML string or file path) |
| `--state-uri` | | `DBT_STATE_URI`, `STATE_URI` | `None` | Remote URI for the state manifest (e.g. `gs://bucket/manifest.json`, `s3://bucket/manifest.json`) |
| `--target-compile` | | `DBT_TARGET_COMPILE` | `false` | Run the second compile pass against the actual target |
| `--skip-reference-compile` | | `DBT_SKIP_REFERENCE_COMPILE` | `false` | Skip the compile pass against the reference/production state |
| `--no-git` | | `DBT_NO_GIT` | `false` | Skip git-based file change comparison |
| `--comparison-strategy` | `--comparison` | `DBT_COMPARISON_STRATEGY` | `hybrid` | Strategy for detecting changed nodes: `dbt`, `git`, or `hybrid` |

> All [common options](#common-options) also apply.

---

### `run` - Run Modified Models

Detects and runs models that have changed. Uses cached state from `init`.

```bash
dbt-ci run --dbt-project-dir dbt --mode models
```

**Flags:**

| Flag | Aliases | Env Var(s) | Default | Description |
|------|---------|-----------|---------|-------------|
| `--mode` | `-m`, `--nodes`, `-n` | `DBT_NODES` | `all` | What to run: `all`, `models`, `seeds`, `snapshots`, `tests` |
| `--filters` | `-f` | | `None` | Extra resource-type filter (repeatable, choices: `models`, `seeds`, `snapshots`, `tests`). E.g. `--mode tests -f snapshots` to run only tests that have a snapshot dependency |

> All [common options](#common-options) also apply.

**Examples:**
```bash
# Run only modified models
dbt-ci run --mode models

# Run modified models with defer to production
dbt-ci run --mode models --defer

# Run all modified resources (models, tests, seeds, etc.)
dbt-ci run --mode all

# With Docker
dbt-ci run --runner docker --mode models
```

---

### `ephemeral` - Ephemeral Environment

Clones changed models and their downstream dependencies into an isolated target schema using **`dbt clone`**, allowing integration testing without affecting production. Uses cached state from `init`.

> **Important:** `--target` and `--vars` must match the environment you want to clone into. The clone operation reads your `profiles.yml` to determine the target database/schema — if these are wrong, models will be cloned to the wrong location or the command will fail.

```bash
dbt-ci ephemeral \
  --target my-pr-env \
  --vars '{"use_production_data":"false"}'
```

**How it works:**
1. Reads the cached change set from `init`
2. Builds a selection of all affected models and their downstream dependencies
3. Runs `dbt clone --select <nodes>` targeting the specified environment
4. The cloned tables/views can then be used as the base for subsequent `dbt run` commands in the PR environment

**Flags:**

| Flag | Aliases | Env Var(s) | Default | Description |
|------|---------|-----------|---------|-------------|
| `--keep-env` | | `DBT_KEEP_ENV` | `false` | Don't destroy the ephemeral environment after the run (if supported by the runner) |

> All [common options](#common-options) also apply.

---

### `delete` - Delete Removed Models

Detects and deletes models that have been removed from the project. Uses cached state from `init`.

```bash
dbt-ci delete --dry-run  # preview what will be deleted
dbt-ci delete            # execute deletions
```

**Flags:**

> Only [common options](#common-options) apply — no command-specific flags.

---

### `finalize` - Finalize State

Run after `run`, `delete`, or `ephemeral` to upload artifacts and clean up the local cache for the next CI run.

```bash
dbt-ci finalize
dbt-ci finalize --artifacts-uri s3://my-bucket/dbt-artifacts/
```

**Flags:**

| Flag | Aliases | Env Var(s) | Default | Description |
|------|---------|-----------|---------|-------------|
| `--artifacts-uri` | | `DBT_ARTIFACTS_URI`, `ARTIFACTS_URI` | `None` | Object storage URI for uploading run artifacts such as the updated `manifest.json` (e.g. `s3://bucket/dbt-artifacts/`) |
| `--clean-ephemeral` | `--destroy-ephemeral` | `DBT_CLEAN_EPHEMERAL`, `DBT_DESTROY_EPHEMERAL` | `false` | Clean up the ephemeral environment as part of finalization |

> All [common options](#common-options) also apply.

## Runners

dbt-ci supports multiple execution environments:

### Local Runner

Execute dbt commands directly on your machine:

```bash
# After init
dbt-ci run \
  --runner local \
  --dbt-project-dir dbt
```

### dbt Runner (Python API)

Uses dbt's Python API (fastest, default):

```bash
# After init - uses dbt Python API
dbt-ci run \
  --runner dbt \
  --dbt-project-dir dbt
```

### Docker Runner

Run dbt commands inside a Docker container:

```bash
dbt-ci run \
  --runner docker \
  --docker-image ghcr.io/dbt-labs/dbt-duckdb:latest \
  --docker-volumes $(pwd):/workspace \
  --dbt-project-dir /workspace/dbt \
  --state /workspace/dbt/.dbtstate
```

**For Apple Silicon Macs:**

```bash
dbt-ci run \
  --runner docker \
  --docker-platform linux/amd64 \
  --docker-image ghcr.io/dbt-labs/dbt-postgres:latest \
  --docker-volumes $(pwd):/workspace \
  --dbt-project-dir /workspace/dbt
```

#### Docker Advanced Options

**Platform (for Apple Silicon compatibility):**
```bash
--docker-platform linux/amd64  # or linux/arm64
```

**Custom Volumes:**
```bash
--docker-volumes "/host/path:/container/path" --docker-volumes "/another:/path:ro"
```

**Environment Variables:**
```bash
--docker-env "DBT_ENV=prod" --docker-env "MY_API_KEY=secret"
```

**Network Mode:**
```bash
--docker-network bridge  # or host, none, container:name
```

**User:**
```bash
--docker-user "1000:1000"  # or leave empty for auto-detect
```

**Additional Docker Args:**
```bash
--docker-args "--memory=2g --cpus=2"
```

**Complete Docker Example:**
```bash
dbt-ci run \
  --runner docker \
  --docker-image ghcr.io/dbt-labs/dbt-postgres:1.7.0 \
  --docker-platform linux/amd64 \
  --docker-env "POSTGRES_HOST=host.docker.internal" \
  --docker-network host \
  --docker-volumes "$(pwd):/workspace" \
  --docker-volumes "$HOME/.aws:/root/.aws:ro" \
  --dbt-project-dir /workspace/dbt \
  --profiles-dir /workspace/dbt \
  --target prod
```

## Common Options

These flags are available on **every** command.

### Configuration File

dbt-ci supports a `dbt-ci.config.yaml` file as an alternative to passing every flag on the command line. It is loaded before any other options so that CLI flags and shell environment variables always take precedence.

**Default location:** `dbt-ci.config.yaml` in the current working directory (override with `--config` / `DBT_CONFIG`).

The file uses a **nested style** where top-level keys map to common options, and command-specific options live under their command's key (`init`, `run`, `finalize`, `ephemeral`, `docker`):

```yaml
# dbt-ci.config.yaml
project_dir: dbt
profiles_dir: dbt
state: dbt/.dbtstate
runner: docker

init:
  state-uri: gs://my-bucket/dbt-state/manifest.json
  reference-target: production
  comparison-strategy: hybrid

finalize:
  artifacts-uri: s3://my-bucket/dbt-artifacts/
  files:
    - manifest
    - cache

docker:
  image: docker.pkg.dev/my-project/dbt:latest
  volumes:
    - "$(pwd)/dbt:/dbt:rw"
    - "${GOOGLE_APPLICATION_CREDENTIALS}:${GOOGLE_APPLICATION_CREDENTIALS}:ro"
  env:
    - "DBT_PROFILES_DIR=/dbt"
    - "GOOGLE_APPLICATION_CREDENTIALS=${GOOGLE_APPLICATION_CREDENTIALS}"
  network: host
```

The legacy flat `DBT_*` key style is also supported:

```yaml
DBT_RUNNER: docker
DBT_PROJECT_DIR: dbt
DBT_STATE: dbt/.dbtstate
```

**Precedence (highest → lowest):**
1. Shell environment variables
2. CLI flags
3. `dbt-ci.config.yaml`
4. Built-in defaults

`${VAR_NAME}` references inside the config file are resolved from the shell environment at load time.

> **Note:** `dbt-ci.config.yaml` is ignored by git by default (it is listed in `.gitignore`). Use it for local developer overrides and commit a `.example` variant for your team.

### Core

| Flag | Aliases | Env Var(s) | Default | Description |
|------|---------|-----------|---------|-------------|
| `--dbt-project-dir` | | `DBT_PROJECT_DIR` | `.` | Path to the dbt project directory |
| `--profiles-dir` | | `DBT_PROFILES_DIR` | Auto-detect | Path to the directory containing `profiles.yml` |
| `--reference-state` | `--state` | `DBT_STATE` | `None` | Local path to the reference state directory (where `manifest.json` is stored) |
| `--target` | `-t` | `DBT_TARGET` | From `profiles.yml` | dbt target to use |
| `--vars` | `-v` | `DBT_VARS` | `""` | YAML string or path to a YAML file with dbt variables |
| `--defer` | | `DBT_DEFER` | `false` | Pass dbt's `--defer` flag (defers unmodified nodes to the production state) |
| `--runner` | `-r` | `DBT_RUNNER` | `dbt` | Runner to use: `dbt`, `local`, `docker`, `bash` |
| `--entrypoint` | | `DBT_ENTRYPOINT` | `dbt` | Command entrypoint for dbt |
| `--dbt-version` | | `DBT_VERSION` | Current | Pin a specific dbt version (e.g. `1.10.13`) |
| `--adapter` | `-a` | `DBT_ADAPTER` | `None` | dbt adapter to install (e.g. `dbt-bigquery`, `dbt-duckdb=1.10.0`) |
| `--config` | `-c` | `DBT_CONFIG` | `dbt-ci.config.yaml` | Path to a dbt-ci YAML configuration file |
| `--dry-run` | | `DBT_DRY_RUN` | `false` | Print commands without executing them |
| `--quiet` | `-q` | `DBT_QUIET` | `false` | Run in quiet mode with minimal output |
| `--log-level` | | `DBT_LOG_LEVEL` | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `--slack-webhook` | `--slack-webhook-url` | `SLACK_WEBHOOK`, `SLACK_WEBHOOK_URL` | `None` | Slack webhook URL for CI notifications |

### Docker Runner

Only used when `--runner docker` is set.

| Flag | Env Var(s) | Default | Description |
|------|-----------|---------|-------------|
| `--docker-image` | `DBT_DOCKER_IMAGE` | `ghcr.io/dbt-labs/dbt-core:latest` | Docker image to use |
| `--docker-platform` | `DBT_DOCKER_PLATFORM` | Auto-detect | Platform override, e.g. `linux/amd64` or `linux/arm64` |
| `--docker-volumes` | `DBT_DOCKER_VOLUMES` | `[]` | Volume mounts (repeatable): `host:container[:mode]` |
| `--docker-env` | `DBT_DOCKER_ENV` | `[]` | Environment variables (repeatable): `KEY=VALUE` |
| `--docker-network` | `DBT_DOCKER_NETWORK` | `host` | Docker network mode |
| `--docker-user` | `DBT_DOCKER_USER` | Auto-detect | User to run as inside the container (`UID:GID`) |
| `--docker-args` | `DBT_DOCKER_ARGS` | `""` | Extra arguments appended to `docker run` |

### Bash Runner

Only used when `--runner bash` is set.

| Flag | Aliases | Env Var(s) | Default | Description |
|------|---------|-----------|---------|-------------|
| `--shell-path` | `--bash-path` | `DBT_SHELL_PATH` | `/bin/bash` | Path to the shell executable |

## Cloud Storage Support

dbt-ci supports storing and retrieving state files from cloud storage (GCS, S3), making it ideal for distributed CI/CD workflows.

### GCS/S3 State Storage

Store your dbt reference state in cloud storage for shared access across CI runs:

```bash
# Initialize and download state from GCS
dbt-ci init \
  --dbt-project-dir dbt \
  --state-uri gs://my-bucket/dbt-state/manifest.json \
  --reference-target production \
  --state dbt/.dbtstate

# Run using cached state (no need to specify URI again)
dbt-ci run --dbt-project-dir dbt --mode models
```

**Benefits:**
- 🔄 **Shared State**: Download the same reference state across different CI jobs
- 💾 **Cache-Based**: After init, commands use local cache (no repeated downloads)
- 📦 **No Git Commits**: State files don't need to be committed to version control
- 🚀 **Scalable**: Works seamlessly in containerized and distributed environments
- 🔐 **Secure**: Leverage cloud IAM and bucket policies for access control

**Configuration:**

The tool uses cloud credentials from your environment. Ensure your bucket is accessible:

```bash
# For GCS
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# For AWS S3
export AWS_ACCESS_KEY_ID=your_key
export AWS_SECRET_ACCESS_KEY=your_secret
export AWS_DEFAULT_REGION=us-east-1

# Or use IAM roles (recommended in CI/CD)
dbt-ci init --state-uri gs://my-bucket/manifest.json
```

**Supported URI Formats:**
- `gs://bucket-name/path/to/manifest.json` (Google Cloud Storage)
- `s3://bucket-name/path/to/manifest.json` (AWS S3)

## Environment Variables

All CLI options can also be set via environment variables:

```bash
export DBT_PROJECT_DIR=./dbt
export DBT_PROFILES_DIR=./dbt
export DBT_TARGET=production
export DBT_RUNNER=local

# After running init, just use:
dbt-ci run
```

**Common Environment Variables:**
- `DBT_PROJECT_DIR` - Path to dbt project
- `DBT_PROFILES_DIR` - Path to profiles.yml location
- `DBT_TARGET` - Target environment to use
- `DBT_RUNNER` - Runner type (local, docker, bash, dbt)

**Note:** State management is cache-based. Run `init` once, then subsequent commands automatically use the cached state.

## CI/CD Integration

### GitHub Actions Example

```yaml
name: dbt CI

on: [pull_request]

jobs:
  dbt-ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Configure AWS Credentials
        uses: aws-actions/configure-aws-credentials@v2
        with:
          role-to-assume: arn:aws:iam::123456789012:role/GitHubActionsRole
          aws-region: us-east-1
      
      - name: Install dbt-ci
        run: pip install git+https://github.com/datablock-dev/dbt-ci.git@main
      
      - name: Initialize dbt-ci with cloud state
        run: |
          dbt-ci init \
            --dbt-project-dir dbt \
            --state-uri gs://my-dbt-state/prod/manifest.json \
            --reference-target production \
            --state dbt/.dbtstate
      
      - name: Run modified models
        run: |
          dbt-ci run --mode models
```

### GitLab CI Example

```yaml
dbt-ci:
  image: python:3.11
  script:
    - pip install git+https://github.com/datablock-dev/dbt-ci.git@main
    - dbt-ci init --dbt-project-dir dbt --state-uri gs://my-dbt-state/prod/manifest.json --reference-target production --state dbt/.dbtstate
    - dbt-ci run --mode models
  only:
    - merge_requests
```

## Features

- **🎯 Smart Detection**: Automatically identifies modified, new, and deleted models
- **📊 Dependency Tracking**: Generates and traverses dependency graphs for lineage analysis
- **🔄 State Comparison**: Compares current state against production for precise CI
- **☁️ Cloud Storage**: S3 integration for shared state across distributed CI/CD workflows
- **🚀 Multiple Runners**: Supports local, Docker, bash, and dbt Python API execution
- **🐳 Docker-First**: Extensive Docker configuration for containerized workflows
- **⚡ Selective Execution**: Run only what changed, saving time and resources
- **🔌 Adapter Support**: Install specific dbt versions and adapters on-demand
- **💬 Notifications**: Slack webhook integration for CI/CD alerts
- **♻️ Ephemeral Environments**: Test changes in isolated environments
- **🧹 Cleanup**: Automatically remove deleted models from target warehouse

## Use Cases

### Pull Request CI
Only build and test models affected by PR changes:
```bash
# Initialize with reference state
dbt-ci init --state-uri gs://bucket/manifest.json --reference-target production --state dbt/.dbtstate

# Run modified models with defer
dbt-ci run --mode models --defer
```

### Distributed CI with Cloud Storage
Share state across multiple CI jobs:
```bash
# Job 1: Initialize state (downloads from cloud)
dbt-ci init --state-uri gs://my-bucket/manifest.json --reference-target production --state dbt/.dbtstate

# Job 2: Run models (uses cached state)
dbt-ci run --mode models

# Job 3: Run tests (uses cached state)
dbt-ci run --mode tests
```

### Selective Testing
Run tests only for modified models:
```bash
# After init
dbt-ci run --mode tests
```

### Schema Migrations
Clean up deleted models from production:
```bash
# After init
dbt-ci delete --target production
```

### Multi-Environment Testing
Create ephemeral test environments:
```bash
dbt-ci ephemeral --keep-env
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

### Development Setup

1. Clone the repository
2. Install dependencies: `pip install -e ".[dev]"`
3. Run tests: `pytest tests/`
4. Run linting: `black src/ tests/`

### Commit Message Format

This project uses [Conventional Commits](https://www.conventionalcommits.org/) for automated releases:

- `feat:` New feature (minor version bump)
- `fix:` Bug fix (patch version bump)
- `docs:` Documentation changes
- `refactor:` Code refactoring
- `test:` Adding tests
- `chore:` Maintenance tasks

Example:
```bash
git commit -m "feat: add Docker runner support"
git commit -m "fix: resolve path resolution on Windows"
```

See [RELEASING.md](RELEASING.md) for details on the automated release process.

## License

See [LICENSE](LICENSE) file for details.

## Links

- **PyPI**: [https://pypi.org/project/dbt-ci/](https://pypi.org/project/dbt-ci/)
- **Documentation**: [https://datablock.dev](https://datablock.dev)
- **Issues**: [GitHub Issues](https://github.com/datablock-dev/dbt-ci/issues)
- **Discussions**: [GitHub Discussions](https://github.com/datablock-dev/dbt-ci/discussions)
- **Changelog**: [CHANGELOG.md](CHANGELOG.md)