# Configuration

[← dbt-ci](../README.md) · [GitHub Action](github-action.md) · [Installation](installation.md) · [Commands](commands.md) · **Configuration** · [Runners](runners.md) · [State storage](state-storage.md) · [CI/CD examples](ci-examples.md)

## Common Options

These flags are available on **every** command.

### Configuration File

dbt-ci supports a `dbt-ci.config.yaml` file as an alternative to passing every flag on the command line. It is loaded before any other options, and a flag passed on the command line always wins over it.

**Default location:** `dbt-ci.config.yaml` in the current working directory (override with `--config` / `DBT_CONFIG`).

If the config file is not found in the current directory, dbt-ci will automatically look for it inside `--dbt-project-dir` (or `DBT_PROJECT_DIR`). This means if your dbt project lives in a subdirectory (e.g. `dbt/`), placing `dbt-ci.config.yaml` there and setting `DBT_PROJECT_DIR=dbt` is enough — no `--config` flag needed.

The file uses a **nested style** where top-level keys map to common options, and command-specific options live under their command's key (`init`, `run`, `finalize`, `ephemeral`, `docker`):

Add the following comment to the top of your `dbt-ci.config.yaml` to get autocompletion and validation in editors that support [yaml-language-server](https://github.com/redhat-developer/yaml-language-server) (e.g. VS Code with the [YAML extension](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml)):

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/datablock-dev/dbt-ci/main/dbt-ci.config.schema.json
```

#### dbt-ci.config.yaml
```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/datablock-dev/dbt-ci/main/dbt-ci.config.schema.json
project_dir: dbt
profiles_dir: dbt
state: dbt/.dbtstate
runner: docker

notifications:
  provider: slack
  format: compact   # the webhook itself is a secret: pass it via SLACK_WEBHOOK
  pr-comment: true  # dbt-ci report also comments on the pull request

init:
  state-uri: gs://my-bucket/dbt-state/manifest.json
  reference-target: production
  comparison-strategy: hybrid
  base-ref: main

run:
  nodes: models
  downstream-depth: 2

finalize:
  artifacts-uri: s3://my-bucket/dbt-artifacts/
  files:
    - manifest
    - cache

docker:
  image: docker.pkg.dev/my-project/dbt:latest
  volumes:
    - "${PWD}/dbt:/dbt:rw"
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
DBT_DOCKER_IMAGE: ghcr.io/dbt-labs/dbt-core:latest
```

Other keys accepted in the config file include `dbt-version`, a `report:` section
(`format`, `output`) and a `notifications:` section (`provider`, `format`, `webhook`,
`pr-comment`), matching the flags of the same names.

**Precedence (highest → lowest):**
1. CLI flags
2. `dbt-ci.config.yaml`
3. Shell environment variables
4. Built-in defaults

The config file sits **above** shell environment variables: a value you commit to
`dbt-ci.config.yaml` is deliberate, whereas the environment a CI runner happens to
export is not. To override a config value per-run, pass the flag rather than setting the
environment variable.

The config file is validated on load. dbt-ci will exit with a clear error message if it contains unknown keys, invalid enum values (e.g. `runner: kubernetes`), or wrong types (e.g. `defer: "yes"` instead of a boolean).

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
| `--defer` | | `DBT_DEFER`, `DEFER_FLAG` | `false` | Pass dbt's `--defer` flag (defers unmodified nodes to the production state). `DEFER_FLAG` is a fallback read only when `DBT_DEFER` is unset, and accepts `--defer`, `--no-defer`, an empty value or a boolean |
| `--runner` | `-r` | `DBT_RUNNER` | `dbt` | Runner to use: `dbt`, `local`, `docker`, `bash` |
| `--entrypoint` | | `DBT_ENTRYPOINT` | `dbt` | Command entrypoint for dbt |
| `--dbt-version` | | `DBT_VERSION` | Current | Pin a specific dbt version (e.g. `1.10.13`, or `2.0.9` for dbt v2). **Requires `--runner local`** |
| `--adapter` | `-a` | `DBT_ADAPTER` | `None` | dbt adapter to install (e.g. `dbt-bigquery`, `dbt-duckdb=1.10.0`). **Requires `--runner local`** |
| `--config` | `-c` | `DBT_CONFIG` | `dbt-ci.config.yaml` | Path to a dbt-ci YAML configuration file |
| `--dry-run` | | `DBT_DRY_RUN` | `false` | Print commands without executing them (and without installing a pinned `--dbt-version`) |
| `--quiet` | `-q` | `DBT_QUIET` | `false` | Run in quiet mode with minimal output |
| `--log-level` | | `DBT_LOG_LEVEL` | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` (dbt's `warn` and `none` are accepted too). dbt reads `DBT_LOG_LEVEL` as well, so dbt-ci rewrites it into dbt's lowercase form (`WARNING` → `warn`, `CRITICAL` → `error`) before running dbt |
| `--slack-webhook` | `--slack-webhook-url`, `--notifications-webhook` | `DBT_NOTIFICATIONS_WEBHOOK`, `SLACK_WEBHOOK`, `SLACK_WEBHOOK_URL` | `None` | Webhook URL for CI notifications (`notifications.webhook` in the config file; the top-level `slack-webhook` key still works). `init` posts a summary of the modified, new and deleted nodes, truncated to the provider's message limit |
| `--notifications-provider` | | `DBT_NOTIFICATIONS_PROVIDER` | `slack` | Service the webhook belongs to (`notifications.provider`). Only `slack` is supported today |
| `--notifications-format` | | `DBT_NOTIFICATIONS_FORMAT` | `default` | Layout of the notification (`notifications.format`): `default` lists each changed node by name, `compact` sends only the counts, `json` sends the changed `unique_id`s as a JSON code block. Every layout opens with a header, the counts and, in GitHub Actions, the repository, branch and a link to the run |

### Docker Runner

Only used when `--runner docker` is set.

| Flag | Env Var(s) | Default | Description |
|------|-----------|---------|-------------|
| `--docker-image` | `DBT_DOCKER_IMAGE` | `ghcr.io/dbt-labs/dbt-core:latest` | Docker image to use |
| `--docker-platform` | `DBT_DOCKER_PLATFORM` | Auto-detect | Platform override, e.g. `linux/amd64` or `linux/arm64` |
| `--docker-volumes` | `DBT_DOCKER_VOLUMES` | `[]` | Volume mounts (repeatable): `host:container[:mode]`. In the env var, separate entries with commas or newlines |
| `--docker-env` | `DBT_DOCKER_ENV` | `[]` | Environment variables (repeatable): `KEY=VALUE`. In the env var, separate entries with newlines, or with a comma followed by the next `KEY=`; spaces and other commas stay part of the value |
| `--docker-network` | `DBT_DOCKER_NETWORK` | `host` | Docker network mode |
| `--docker-user` | `DBT_DOCKER_USER` | Invoking user (`uid:gid`) | User to run as inside the container (`UID:GID`). Defaults to the UID and GID of the process running dbt-ci so container-written files are owned by the invoking user. |
| `--docker-args` | `DBT_DOCKER_ARGS` | `""` | Extra arguments appended to `docker run` |

### Pinning a dbt version or adapter

`--dbt-version` and `--adapter` install the requested packages into a cached virtual
environment under `~/.cache/dbt-ci/venvs/` and run dbt from it. Only the **`local`**
runner can execute an arbitrary dbt binary, so the pin applies there:

```bash
dbt-ci run --runner local --dbt-version 1.10.13 --adapter dbt-duckdb=1.10.0
```

Adapters may be given with or without a version (`dbt-bigquery`, `dbt-bigquery=1.10.0`,
`dbt-bigquery==1.10.0`). Each version/adapter combination gets its own cached
environment, and an interrupted install is rebuilt on the next run rather than reused.

The other runners resolve dbt from elsewhere and log a warning if a pin is set:

| Runner | dbt comes from |
|--------|----------------|
| `dbt` | the `dbt-core` installed alongside dbt-ci (runs in-process) |
| `docker` | the configured `--docker-image` |
| `bash` | the script at `--shell-path`, or `--entrypoint` run through it when `--shell-path` is a shell such as `/bin/bash` |

### dbt v2

dbt v2 is a ground-up rewrite of dbt in Rust. It ships on PyPI as `dbt` (or `dbt-oss`)
rather than `dbt-core`, as a self-contained binary with every adapter bundled. dbt-ci
drives it through the CLI, so use the **`local`** or **`docker`** runner:

```bash
# dbt-ci installs dbt v2 into a cached virtual environment
dbt-ci init --runner local --dbt-version 2.0.9 ...
dbt-ci run  --runner local --dbt-version 2.0.9 ...

# ...or point dbt-ci at a dbt v2 binary you installed yourself
dbt-ci run --runner local --entrypoint /path/to/dbt ...

# ...or run dbt v2 from a Docker image
dbt-ci run --runner docker --docker-image my-registry/dbt-v2:2.0.9 ...
```

With the Docker runner, dbt-ci passes the dbt command (`ls ...`, `run ...`) as the
container command, so the image's entrypoint must be `dbt`, as in the official dbt
images. The default `--docker-image` is a dbt-core 1.x image, so pass a dbt v2 image
explicitly. A minimal one:

```dockerfile
FROM python:3.12-slim
RUN pip install --no-cache-dir "dbt==2.0.9"
ENTRYPOINT ["dbt"]
```

Things to know:

- **Keep dbt v2 out of dbt-ci's environment.** dbt-ci depends on dbt-core 1.x, and dbt v2
  and dbt-core both install a `dbt` Python package and `dbt` executable, so installing
  them into one environment overwrites one with the other. Install dbt-ci on its own
  (e.g. `pipx install dbt-ci` or `uv tool install dbt-ci`) and let `--dbt-version`
  or `--entrypoint` supply dbt v2, or run dbt v2 from an image with `--runner docker`.
- **The `dbt` runner is v1 only.** It runs the dbt-core installed alongside dbt-ci
  in-process.
- **`--adapter` is ignored for dbt v2**, because adapters are bundled. A warning is logged.
- **Deferral stays opt-in.** dbt v2 defers to `--state` by default, while dbt v1 only
  defers when asked. dbt-ci passes `--no-defer` whenever it passes `--state` without
  `--defer`, so `run`, `test` and `build` behave the same on both versions. `--defer`
  (or `DBT_DEFER`, or `DEFER_FLAG=--defer`) still turns deferral on.
- **Change detection works unchanged.** dbt v2 still writes `target/manifest.json` in the
  same v12 schema dbt-ci parses. CI checks every manifest field dbt-ci relies on (node
  ids, resource types, project-relative file paths, configs, lineage) against dbt-core
  1.10, 1.11, 1.12 and dbt v2, through both the local and the Docker runner.
- **Upgrading mid-stream is supported.** A reference state built with dbt-core 1.x can be
  compared against a PR that runs dbt v2, so CI keeps working while production is still
  on 1.x. Once production runs dbt v2, refresh the stored state so both sides match.

### Bash Runner

Only used when `--runner bash` is set.

| Flag | Aliases | Env Var(s) | Default | Description |
|------|---------|-----------|---------|-------------|
| `--shell-path` | `--bash-path` | `DBT_SHELL_PATH` | `/bin/bash` | Path to a dbt wrapper script, which receives the dbt arguments directly, or to a shell (`bash`, `sh`, `zsh`, `dash`, `ksh`), which runs `--entrypoint` (default `dbt`) with them |

The bash runner gets the same absolute `--project-dir`, `--profiles-dir` and `--state` paths as the `local` runner.

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
- `DBT_CI_CACHE_DIR` - Where the state cache and log file live (default: `<temp dir>/dbt-ci`)

**Note:** State management is cache-based. Run `init` once, then subsequent commands automatically use the cached state.

### Settings Inherited From `init`

`init` records the `--target`, `--vars` and `--state` it ran with, and later commands reuse
them, so they only need to be given once:

```bash
dbt-ci init --target ci --vars '{"use_production_data": false}' --state dbt/.dbtstate
dbt-ci run          # runs against target 'ci' with the same vars
dbt-ci delete       # likewise
```

The state path is recorded even when `init` chose it: with `--state-uri` and no `--state`,
the manifest is downloaded to `<dbt-project-dir>/.dbtstate`, and later commands such as
`ephemeral` pass that directory to dbt as `--state` (needed for `dbt clone` and other
deferring commands).

Passing the flag explicitly still wins — the cache only fills in what was left unset.

### Cache Location

`init` writes its cache (state comparison, manifests, run report and log file) to
`<temp dir>/dbt-ci`, and later commands read it from there. Because the location is
fixed, two dbt-ci runs executing at the same time on the same machine — for example two
pull request jobs on a shared self-hosted runner — would overwrite each other's state.

Set `DBT_CI_CACHE_DIR` to give each run its own directory:

```bash
export DBT_CI_CACHE_DIR="/tmp/dbt-ci-${GITHUB_RUN_ID}"
dbt-ci init ...
dbt-ci run ...
```

All commands in the same CI job must see the same value, since that is how `run`,
`delete`, `ephemeral` and `finalize` find the cache written by `init`.
