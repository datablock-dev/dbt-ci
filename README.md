# dbt-ci

A CI tool for dbt (data build tool) projects that helps identify and run modified models based on state comparison.

## Installation

### Local Installation

```bash
pip install -e .
```

### Installation through 
```bash
pip install git+https://github.com/datablock-dev/dbt-ci.git@main
```
## Usage

### Local Runner

Run dbt commands locally:

```bash
python main.py \
  --prod-manifest-dir dbt/.dbtstate \
  --dbt-project-dir dbt \
  --runner local
```

### Docker Runner

Run dbt commands inside a Docker container:

```bash
python main.py \
  --prod-manifest-dir dbt/.dbtstate \
  --dbt-project-dir dbt \
  --runner docker \
  --docker-image ghcr.io/dbt-labs/dbt-postgres:latest
```

**For Apple Silicon Macs:**

If the Docker image doesn't have ARM64 support, use the `--docker-platform` flag:

```bash
python main.py \
  --prod-manifest-dir dbt/.dbtstate \
  --dbt-project-dir dbt \
  --runner docker \
  --docker-image ghcr.io/dbt-labs/dbt-postgres:latest \
  --docker-platform linux/amd64
```

#### Docker Advanced Options

**Platform (for Apple Silicon compatibility):**
```bash
--docker-platform linux/amd64  # or linux/arm64
```

**Custom Volumes:**
```bash
--docker-volumes "/host/path:/container/path" "/another:/path:ro"
```

**Environment Variables:**
```bash
--docker-env "DBT_ENV=prod" "MY_API_KEY=secret"
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

**Complete Example:**
```bash
python main.py \
  --prod-manifest-dir dbt/.dbtstate \
  --dbt-project-dir dbt \
  --profiles-dir ~/.dbt \
  --runner docker \
  --docker-image ghcr.io/dbt-labs/dbt-postgres:1.7.0 \
  --docker-platform linux/amd64 \
  --docker-env "POSTGRES_HOST=host.docker.internal" \
  --docker-network host \
  --docker-volumes "$HOME/.aws:/root/.aws:ro" \
  --target prod
```

## CLI Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--prod-manifest-dir` | Directory containing production manifest.json | Required |
| `--dbt-project-dir` | Path to dbt project | `.` |
| `--profiles-dir` | Path to profiles.yml directory | Auto-detect |
| `--target` | dbt target to use | From profiles.yml |
| `--runner` | Runner type: `local` or `docker` | `local` |
| `--docker-image` | Docker image for dbt | `ghcr.io/dbt-labs/dbt-postgres:latest` |
| `--docker-platform` | Platform for Docker image (linux/amd64, linux/arm64) | Auto-detect |
| `--docker-volumes` | Additional volume mounts | `[]` |
| `--docker-env` | Environment variables | `[]` |
| `--docker-network` | Docker network mode | `host` |
| `--docker-user` | User to run as (UID:GID) | Auto-detect |
| `--docker-args` | Additional docker run args | `""` |
| `--dry-run` | Print commands without executing | `false` |

## Features

- **State Comparison**: Identifies modified models between current and production state
- **Dependency Graph**: Generates dependency graph for lineage analysis
- **Multiple Runners**: Supports both local and Docker execution
- **Flexible Configuration**: Extensive Docker configuration options for CI/CD pipelines