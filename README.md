# dbt-ci

A CI tool for dbt (data build tool) projects that intelligently runs only modified models based on state comparison, supporting multiple execution environments including local, Docker, and dbt runners.

## Installation

### Local Development

```bash
pip install -e .
```

### From GitHub

```bash
pip install git+https://github.com/datablock-dev/dbt-ci.git@main
```

After installation, the tool is available as `dbt-ci`.

## Quick Start

### 1. Initialize State

First, initialize the dbt-ci state by compiling your project and creating a baseline:

```bash
dbt-ci init \
  --dbt-project-dir dbt \
  --profiles-dir dbt \
  --production-target production
```

### 2. Run Modified Models

After making changes to your dbt project, run only the modified models:

```bash
dbt-ci run \
  --dbt-project-dir dbt \
  --profiles-dir dbt \
  --state dbt/.dbtstate
```

## Commands

### `init` - Initialize State

Creates initial state from your dbt project. **Always run this first.**

```bash
dbt-ci init \
  --dbt-project-dir dbt \
  --profiles-dir dbt \
  --production-target production
```

**Options:**
- `--production-target`: Target to use for production/reference manifest (optional)
- `--dbt-version`: Specific dbt version to use (e.g., `1.10.13`)
- `--adapter`, `-a`: Adapter to install (e.g., `dbt-duckdb=1.10.0`)

### `run` - Run Modified Models

Detects and runs models that have changed:

```bash
dbt-ci run \
  --dbt-project-dir dbt \
  --state dbt/.dbtstate \
  --mode models
```

**Options:**
- `--mode`, `-m`: What to run: `all`, `models`, `seeds`, `snapshots`, `tests` (default: `all`)
- `--levels`: Number of dependency levels to include
- `--defer`: Use dbt's defer flag for production state

**Examples:**
```bash
# Run only modified models
dbt-ci run --mode models

# Run modified models with 2 levels of dependencies
dbt-ci run --mode models --levels 2

# Run all modified resources (models, tests, seeds, etc.)
dbt-ci run --mode all
```

### `ephemeral` - Ephemeral Environment

Creates ephemeral environments for testing without affecting production:

```bash
dbt-ci ephemeral \
  --dbt-project-dir dbt \
  --state dbt/.dbtstate
```

**Options:**
- `--keep-env`: Don't destroy ephemeral environment after run

### `delete` - Delete Removed Models

Detects and deletes models that have been removed from the project:

```bash
dbt-ci delete \
  --dbt-project-dir dbt \
  --state dbt/.dbtstate
```

## Runners

dbt-ci supports multiple execution environments:

### Local Runner

Execute dbt commands directly on your machine:

```bash
dbt-ci run \
  --runner local \
  --dbt-project-dir dbt \
  --state dbt/.dbtstate
```

### dbt Runner (Python API)

Uses dbt's Python API (fastest, default):

```bash
dbt-ci run \
  --runner dbt \
  --dbt-project-dir dbt \
  --state dbt/.dbtstate
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

## Global Options

These options apply to all commands:

| Option | Description | Default |
|--------|-------------|---------|
| `--dbt-project-dir` | Path to dbt project directory | `.` |
| `--profiles-dir` | Path to profiles.yml directory | Auto-detect |
| `--state`, `--reference-manifest-dir` | Directory containing reference manifest.json | Required for run/delete |
| `--production-target` | dbt target for production/reference manifest | None |
| `--target`, `-t` | dbt target to use | From profiles.yml |
| `--vars`, `-v` | YAML string or file path with dbt variables | `""` |
| `--defer` | Use dbt's defer flag for production state | `false` |
| `--runner`, `-r` | Runner type: `local`, `docker`, `bash`, `dbt` | `dbt` |
| `--entrypoint` | Command entrypoint for dbt | `dbt` |
| `--dbt-version` | Specific dbt version to use | Current |
| `--adapter`, `-a` | Adapter to install (format: `dbt-adapter=version`) | None |
| `--dry-run` | Print commands without executing | `false` |
| `--log-level` | Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL | `INFO` |
| `--slack-webhook` | Slack webhook URL for notifications | None |

### Docker Options

| Option | Description | Default |
|--------|-------------|---------|
| `--docker-image` | Docker image for dbt | `ghcr.io/dbt-labs/dbt-core:latest` |
| `--docker-platform` | Platform (linux/amd64, linux/arm64) | Auto-detect |
| `--docker-volumes` | Volume mounts (format: `host:container[:mode]`) | `[]` |
| `--docker-env` | Environment variables (format: `KEY=VALUE`) | `[]` |
| `--docker-network` | Docker network mode | `host` |
| `--docker-user` | User to run as (UID:GID) | Auto-detect |
| `--docker-args` | Additional docker run arguments | `""` |

### Bash Runner Options

| Option | Description | Default |
|--------|-------------|---------|
| `--shell-path`, `--bash-path` | Path to shell executable | `/bin/bash` |

## Environment Variables

All CLI options can also be set via environment variables:

```bash
export DBT_PROJECT_DIR=./dbt
export DBT_PROFILES_DIR=./dbt
export DBT_STATE=./dbt/.dbtstate
export DBT_TARGET=production
export DBT_RUNNER=local

dbt-ci run
```

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
      
      - name: Install dbt-ci
        run: pip install git+https://github.com/datablock-dev/dbt-ci.git@main
      
      - name: Initialize dbt-ci
        run: |
          dbt-ci init \
            --dbt-project-dir dbt \
            --production-target production
      
      - name: Run modified models
        run: |
          dbt-ci run \
            --mode models \
            --state dbt/.dbtstate
```

### GitLab CI Example

```yaml
dbt-ci:
  image: python:3.11
  script:
    - pip install git+https://github.com/datablock-dev/dbt-ci.git@main
    - dbt-ci init --dbt-project-dir dbt --production-target production
    - dbt-ci run --mode models --state dbt/.dbtstate
  only:
    - merge_requests
```

## Features

- **🎯 Smart Detection**: Automatically identifies modified, new, and deleted models
- **📊 Dependency Tracking**: Generates and traverses dependency graphs for lineage analysis
- **🔄 State Comparison**: Compares current state against production for precise CI
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
dbt-ci init --production-target production
dbt-ci run --mode models --defer
```

### Selective Testing
Run tests only for modified models:
```bash
dbt-ci run --mode tests --state dbt/.dbtstate
```

### Schema Migrations
Clean up deleted models from production:
```bash
dbt-ci delete --target production
```

### Multi-Environment Testing
Create ephemeral test environments:
```bash
dbt-ci ephemeral --keep-env
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

See [LICENSE](LICENSE) file for details.

## Links

- **Documentation**: [https://datablock.dev](https://datablock.dev)
- **Issues**: [GitHub Issues](https://github.com/datablock-dev/dbt-ci/issues)
- **Discussions**: [GitHub Discussions](https://github.com/datablock-dev/dbt-ci/discussions)