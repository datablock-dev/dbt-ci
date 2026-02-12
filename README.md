# dbt-ci

A CI tool for dbt (data build tool) projects that intelligently runs only modified models based on state comparison, supporting multiple execution environments including local, Docker, and dbt runners.

## Installation

### From PyPI (Recommended)

```bash
pip install dbt-ci
```

### From GitHub

```bash
pip install git+https://github.com/datablock-dev/dbt-ci.git@main
```

### Local Development

```bash
git clone https://github.com/datablock-dev/dbt-ci.git
cd dbt-ci
pip install -e ".[dev]"
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

**With Cloud Storage (S3):**
```bash
dbt-ci init \
  --dbt-project-dir dbt \
  --state-uri s3://my-bucket/dbt-state/ \
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

**Or from S3:**
```bash
dbt-ci run \
  --dbt-project-dir dbt \
  --state-uri s3://my-bucket/dbt-state/
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

**With Cloud Storage:**
```bash
dbt-ci run \
  --dbt-project-dir dbt \
  --state-uri s3://my-bucket/dbt-state/ \
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

# Run with cloud storage
dbt-ci run --state-uri s3://my-bucket/state/ --mode models
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
| `--state`, `--reference-state` | Path to the reference manifest.json directory | Required for run/delete |
| `--state-uri` | Cloud storage URI for state files (e.g., `s3://bucket/path/`) | None |
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

## Cloud Storage Support

dbt-ci supports storing and retrieving state files from cloud storage, making it ideal for distributed CI/CD workflows.

### S3 State Storage

Store your dbt state in S3 for shared access across CI runs:

```bash
# Initialize and upload state to S3
dbt-ci init \
  --dbt-project-dir dbt \
  --state-uri s3://my-bucket/dbt-state/ \
  --production-target production

# Run using state from S3
dbt-ci run \
  --dbt-project-dir dbt \
  --state-uri s3://my-bucket/dbt-state/ \
  --mode models
```

**Benefits:**
- 🔄 **Shared State**: Access the same state across different CI jobs and environments
- 📦 **No Local Storage**: State files don't need to be committed to git
- 🚀 **Scalable**: Works seamlessly in containerized and distributed environments
- 🔐 **Secure**: Leverage AWS IAM and S3 bucket policies for access control

**Configuration:**

The tool uses AWS credentials from your environment (AWS CLI, IAM roles, environment variables). Ensure your S3 bucket is accessible:

```bash
# AWS credentials via environment
export AWS_ACCESS_KEY_ID=your_key
export AWS_SECRET_ACCESS_KEY=your_secret
export AWS_DEFAULT_REGION=us-east-1

# Or use IAM roles (recommended in CI/CD)
dbt-ci run --state-uri s3://my-bucket/dbt-state/
```

**Supported URI Formats:**
- `s3://bucket-name/path/to/state/`
- `s3://bucket-name/dbt-state/`

## Environment Variables

All CLI options can also be set via environment variables:

```bash
export DBT_PROJECT_DIR=./dbt
export DBT_PROFILES_DIR=./dbt
export DBT_STATE=./dbt/.dbtstate
export DBT_STATE_URI=s3://my-bucket/dbt-state/
export DBT_TARGET=production
export DBT_RUNNER=local

dbt-ci run
```

**Common Environment Variables:**
- `DBT_STATE` or `STATE_DIR` - Local path to state directory
- `DBT_STATE_URI` or `STATE_URI` - Cloud storage URI for state files
- `DBT_PROJECT_DIR` - Path to dbt project
- `DBT_PROFILES_DIR` - Path to profiles.yml location
- `DBT_TARGET` - Target environment to use
- `DBT_RUNNER` - Runner type (local, docker, bash, dbt)

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
      
      - name: Initialize dbt-ci with S3 state
        run: |
          dbt-ci init \
            --dbt-project-dir dbt \
            --state-uri s3://my-dbt-state/prod/ \
            --production-target production
      
      - name: Run modified models
        run: |
          dbt-ci run \
            --mode models \
            --state-uri s3://my-dbt-state/prod/
```

### GitLab CI Example

```yaml
dbt-ci:
  image: python:3.11
  script:
    - pip install git+https://github.com/datablock-dev/dbt-ci.git@main
    - dbt-ci init --dbt-project-dir dbt --state-uri s3://my-dbt-state/prod/ --production-target production
    - dbt-ci run --mode models --state-uri s3://my-dbt-state/prod/
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
dbt-ci init --production-target production
dbt-ci run --mode models --defer
```

### Distributed CI with Cloud Storage
Share state across multiple CI jobs using S3:
```bash
# Job 1: Initialize state
dbt-ci init --state-uri s3://my-bucket/dbt-state/ --production-target production

# Job 2: Run models
dbt-ci run --state-uri s3://my-bucket/dbt-state/ --mode models

# Job 3: Run tests
dbt-ci run --state-uri s3://my-bucket/dbt-state/ --mode tests
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