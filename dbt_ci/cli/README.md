# dbt-ci Configuration

All CLI flags can be set via a YAML config file, environment variables, or passed directly as flags. The order of precedence (highest to lowest) is:

```
CLI flag > environment variable > config file value > default
```

---

## Config File

By default, dbt-ci looks for `dbt-ci.config.yaml` in the current working directory. Override this with:

```bash
dbt-ci init --config path/to/my-config.yaml
# or
export DBT_CONFIG=path/to/my-config.yaml
```

The config file uses YAML format where each key is the corresponding environment variable name:

```yaml
# dbt-ci.config.yaml
DBT_PROJECT_DIR: "dbt"
DBT_PROFILES_DIR: "dbt"
DBT_STATE: "dbt/.dbtstate"
DBT_RUNNER: "docker"
DBT_DOCKER_IMAGE: "my-registry/dbt:latest"
DBT_DOCKER_VOLUMES:
  - "dbt:/dbt:rw"
  - "${GOOGLE_APPLICATION_CREDENTIALS}:${GOOGLE_APPLICATION_CREDENTIALS}:ro"
DBT_DOCKER_ENV:
  - "DBT_PROFILES_DIR=/dbt"
  - "GOOGLE_APPLICATION_CREDENTIALS=${GOOGLE_APPLICATION_CREDENTIALS}"
```

> Shell environment variables set before running dbt-ci always take precedence over values in the config file.

---

## All Configuration Keys

### Core

| Key | CLI Flag | Default | Description |
|-----|----------|---------|-------------|
| `DBT_CONFIG` | `--config`, `-c` | `dbt-ci.config.yaml` | Path to the config file itself |
| `DBT_PROJECT_DIR` | `--dbt-project-dir` | `.` | Path to the dbt project directory |
| `DBT_PROFILES_DIR` | `--profiles-dir` | `None` | Path to directory containing `profiles.yml` |
| `DBT_STATE` | `--state` | `None` | Local path where the reference manifest is stored/downloaded |
| `DBT_TARGET` | `--target`, `-t` | profiles.yml default | dbt target to use |
| `DBT_VARS` | `--vars`, `-v` | `""` | YAML string or path to YAML file with dbt variables |
| `DBT_RUNNER` | `--runner`, `-r` | `dbt` | Runner: `dbt`, `local`, `docker`, `bash` |
| `DBT_ENTRYPOINT` | `--entrypoint` | `dbt` | Command entrypoint for dbt |
| `DBT_ADAPTER` | `--adapter`, `-a` | `None` | dbt adapter (e.g. `bigquery`, `postgres`) |
| `DBT_VERSION` | `--dbt-version` | `None` | dbt version override |
| `DBT_DEFER` | `--defer` | `false` | Enable dbt `--defer` flag |
| `DBT_DRY_RUN` | `--dry-run` | `false` | Print commands without executing |
| `DBT_LOG_LEVEL` | `--log-level` | `INFO` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `DBT_QUIET` | `--quiet`, `-q` | `false` | Minimal output mode |

### Notifications

| Key | CLI Flag | Default | Description |
|-----|----------|---------|-------------|
| `SLACK_WEBHOOK` | `--slack-webhook` | `None` | Slack webhook URL for notifications |

### Docker Runner

Only used when `DBT_RUNNER=docker`.

| Key | CLI Flag | Default | Description |
|-----|----------|---------|-------------|
| `DBT_DOCKER_IMAGE` | `--docker-image` | `ghcr.io/dbt-labs/dbt-core:latest` | Docker image to use |
| `DBT_DOCKER_PLATFORM` | `--docker-platform` | `None` | Platform (e.g. `linux/amd64`) |
| `DBT_DOCKER_VOLUMES` | `--docker-volumes` | `[]` | Volume mounts (`host:container[:mode]`). List in YAML, comma-separated in env var. |
| `DBT_DOCKER_ENV` | `--docker-env` | `[]` | Environment variables to inject (`KEY=VALUE`). List in YAML, comma-separated in env var. |
| `DBT_DOCKER_NETWORK` | `--docker-network` | `host` | Docker network mode |
| `DBT_DOCKER_USER` | `--docker-user` | `None` | User to run as inside the container |
| `DBT_DOCKER_ARGS` | `--docker-args` | `""` | Extra `docker run` arguments |

### Bash Runner

Only used when `DBT_RUNNER=bash`.

| Key | CLI Flag | Default | Description |
|-----|----------|---------|-------------|
| `DBT_SHELL_PATH` | `--shell-path` | `/bin/bash` | Path to shell executable |

---

## Runners

| Runner | Description |
|--------|-------------|
| `dbt` | Invokes `dbt` directly from PATH (default) |
| `local` | Runs dbt via the installed Python package |
| `docker` | Runs dbt inside a Docker container |
| `bash` | Runs dbt commands via a shell script |

---

## Tips

**Multiple volumes/env vars in a YAML config** — use a list:
```yaml
DBT_DOCKER_VOLUMES:
  - "dbt:/dbt:rw"
  - "/credentials:/credentials:ro"
```

**Multiple volumes/env vars as an environment variable** — use comma or newline separation:
```bash
export DBT_DOCKER_VOLUMES="dbt:/dbt:rw,/credentials:/credentials:ro"
```

**JSON Schema validation** — a JSON Schema is provided at `dbt-ci.config.schema.json` in the project root. Configure your editor to validate `dbt-ci.config.yaml` against it:

*VS Code (`settings.json`):*
```json
"yaml.schemas": {
  "./dbt-ci.config.schema.json": "dbt-ci.config.yaml"
}
```
