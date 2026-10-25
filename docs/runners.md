# Runners

[← dbt-ci](../README.md) · [GitHub Action](github-action.md) · [Installation](installation.md) · [Commands](commands.md) · [Configuration](configuration.md) · **Runners** · [State storage](state-storage.md) · [CI/CD examples](ci-examples.md)

dbt-ci supports multiple execution environments:

## Local Runner

Execute dbt commands directly on your machine:

```bash
# After init
dbt-ci run \
  --runner local \
  --dbt-project-dir dbt
```

## dbt Runner (Python API)

Uses dbt's Python API (fastest, default):

```bash
# After init - uses dbt Python API
dbt-ci run \
  --runner dbt \
  --dbt-project-dir dbt
```

## Docker Runner

Run dbt commands inside a Docker container. Requires `pip install 'dbt-ci[docker]'`:

```bash
dbt-ci run \
  --runner docker \
  --docker-image ghcr.io/dbt-labs/dbt-duckdb:latest \
  --docker-volumes "$(pwd)/dbt:/dbt:rw"
```

When using the Docker runner, `--project-dir`, `--profiles-dir`, and `--state` are derived from the volume map — if the host path is inside a mounted volume (compared by path, so a `dbt` mount does not cover `dbt_project`), the corresponding container path is passed to dbt inside the container; with nested mounts the most specific one wins. `DBT_PROJECT_DIR`, `DBT_PROFILES_DIR` or `DBT_STATE` in `--docker-env` take priority. If no matching volume is found, `--project-dir` and `--profiles-dir` are omitted and dbt falls back to its own defaults (typically the container's `WORKDIR`), while `--state` is passed through unchanged so an absolute container path can be given directly.

**For Apple Silicon Macs:**

```bash
dbt-ci run \
  --runner docker \
  --docker-platform linux/amd64 \
  --docker-image ghcr.io/dbt-labs/dbt-postgres:latest \
  --docker-volumes "$(pwd)/dbt:/dbt:rw"
```

### Docker Advanced Options

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

dbt-ci drives Docker through the Python SDK rather than the `docker` CLI, so `--docker-args` supports the subset of `docker run` flags that map onto SDK options. Both `--flag value` and `--flag=value` spellings work:

| Supported in `--docker-args` | Effect |
|------------------------------|--------|
| `--memory` / `-m` | Container memory limit |
| `--cpus` | CPU quota |
| `--shm-size` | Size of `/dev/shm` |
| `--env` / `-e` | Extra environment variables (merged with `--docker-env`) |
| `--add-host` | Extra host-to-IP mappings |
| `--workdir` / `-w` | Working directory inside the container |
| `--hostname` | Container hostname |
| `--privileged` | Extended privileges |
| `--platform`, `--network` | Override `--docker-platform` / `--docker-network` |

Anything else is logged as ignored rather than dropped silently.

> **Note:** containers are removed once the command finishes, so repeated CI runs don't accumulate stopped containers.

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
  --target prod
```
