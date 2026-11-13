# Configuration

[← dbt-ci](../README.md) · [GitHub Action](github-action.md) · [Installation](installation.md) · [Commands](commands.md) · **Configuration** · [Runners](runners.md) · [State storage](state-storage.md) · [CI/CD examples](ci-examples.md)

## Common Options

These flags are available on **every** command.

### Configuration File

dbt-ci supports a `dbt-ci.config.yaml` file as an alternative to passing every flag on the command line. It is loaded before any other options, and a flag passed on the command line always wins over it.

**Default location:** `dbt-ci.config.yaml` in the current working directory (override with `--config` / `DBT_CONFIG`).

If the config file is not found in the current directory, dbt-ci will automatically look for it inside `--dbt-project-dir` (or `DBT_PROJECT_DIR`). This means if your dbt project lives in a subdirectory (e.g. `dbt/`), placing `dbt-ci.config.yaml` there and setting `DBT_PROJECT_DIR=dbt` is enough — no `--config` flag needed.

The file uses a **nested style** where top-level keys map to common options, and command-specific options live under their command's key (see [Sections](#sections)).

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
  compare-to: auto   # auto | merge-base | latest

run:
  nodes: models
  downstream-depth: 2
  skip-test-only-changes: true
  retries: 2         # retry a failed step with dbt retry

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

Other keys accepted in the config file are listed under [Sections](#sections).

**Precedence (highest → lowest):**
1. CLI flags
2. The [`on:` block](#settings-per-ci-event) for the run's event: the selected profile's,
   then the top level's
3. The selected [profile](#profiles) in `dbt-ci.config.yaml`
4. The top-level settings in `dbt-ci.config.yaml`
5. Shell environment variables
6. Built-in defaults

**Empty values count as not set.** A flag given an empty value (`--vars ''` or
`--vars=`), an empty value in the config file (`target: ""`, or a `${VAR}` that is set but
empty) and an empty environment variable are all ignored, so the next source in the list
applies. This keeps CI templates such as `--vars '${{ inputs.vars }}'` from wiping the
config file, the selected profile or what `init` recorded when the input is empty. To
pass empty dbt vars on purpose, use `--vars '{}'`.

To see which value won and why, run [`dbt-ci config show`](commands.md#config-show---show-resolved-settings)
with the command and flags you plan to use, e.g. `dbt-ci config show run --profile action`.

The config file sits **above** shell environment variables: a value you commit to
`dbt-ci.config.yaml` is deliberate, whereas the environment a CI runner happens to
export is not. To override a config value per-run, pass the flag rather than setting the
environment variable.

The config file is validated on load. dbt-ci will exit with a clear error message if it contains unknown keys, invalid enum values (e.g. `runner: kubernetes`), or wrong types (e.g. `defer: "yes"` instead of a boolean).

`${VAR_NAME}` references inside the config file are resolved from the shell environment at load time.

#### Sections

| Section | Keys |
|---|---|
| Top level | The [common options](#core): `project-dir`, `profiles-dir`, `state`, `target`, `vars`, `defer`, `dry-run`, `runner`, `entrypoint`, `dbt-version`, `adapter`, `log-level`, `quiet`, `shell-path` |
| `init` | `reference-target`, `reference-vars`, `state-uri`, `reference-path`, `target-compile`, `skip-reference-compile`, `comparison-strategy`, `base-ref`, `compare-to` |
| `run` | `nodes`, `downstream-depth`, `filters`, `select`, `exclude`, `skip-test-only-changes`, `retries` |
| `ephemeral` | `dry-run` (for `ephemeral create` and `ephemeral destroy`), `keep-env` (deprecated) |
| `delete` | `dry-run` |
| `migration` | `dry-run` |
| `finalize` | `artifacts-uri`, `files`, `force-manifest`, `clean-ephemeral` |
| `report` | `format`, `output` |
| `notifications` | `provider`, `format`, `webhook`, `pr-comment` |
| `docker` | `image`, `platform`, `volumes`, `env`, `network`, `user`, `args` |
| `profiles` | Named sets of the keys above; see [Profiles](#profiles) |
| `on` | The keys above per CI event; see [Settings per CI event](#settings-per-ci-event) |

Keys match the flags of the same names. Hyphens and underscores are interchangeable
(`dry-run` or `dry_run`).

**Dry run per command.** The top-level `dry-run` applies to every command, `run`
included. `delete`, `migration` and `ephemeral` also read a `dry-run` key of their own,
so they can preview what they would change while `run` still builds:

```yaml
delete:
  dry-run: true
migration:
  dry-run: true
```

For those three commands, the order is: `--dry-run` on the command line, the command's
own `dry-run` (from the top level, a profile or an `on:` block, layered as usual), the
top-level `dry-run`, `DBT_DRY_RUN`, then `false`. `delete.dry-run: false` therefore runs
`delete` for real even when the top-level `dry-run` is `true`. `dbt-ci config show delete`
shows which layer set it.

#### Profiles

One config file can serve several contexts, such as a CI pipeline, a sandbox and
production. Put the settings they share at the top level, and what differs under
`profiles`:

```yaml
# Shared by every profile
project-dir: dbt
profiles-dir: dbt
init:
  reference-target: production
  comparison-strategy: dbt

profiles:
  action:
    target: ci
    defer: true
    init:
      state-uri: gs://my-bucket/dbt-state/manifest.json

  sandbox:
    target: sandbox
    init:
      state-uri: gs://my-bucket/sandbox/manifest.json
```

Select a profile with `--profile` (or `DBT_CI_PROFILE`, or the GitHub Action's `profile`
input):

```bash
dbt-ci init --profile action   # target ci, the production manifest, and init.reference-target from the top level
dbt-ci run                     # reuses profile 'action'
```

- A profile takes the same keys as the top level, in the same places: `target`, `vars`
  and `defer` at the top of the profile, `reference-target` and `state-uri` under `init`,
  and so on. Profiles cannot contain `profiles`.
- A profile's values are applied over the top-level ones, key by key. Lists replace the
  top-level list rather than extending it, so a profile's `docker.volumes` is the
  complete list.
- `init` records the profile it ran with, and later commands (`run`, `ephemeral`,
  `report`, `finalize`, ...) reuse it, like the [settings inherited from
  `init`](#settings-inherited-from-init). Passing `--profile` to a later command still
  wins.
- A profile's name is only a label. It is never used as the dbt target: a profile
  without `target` uses the top-level `target`, then `DBT_TARGET`, and otherwise dbt's
  default target from `profiles.yml`.
- An unknown profile name fails with the list of profiles the file defines. Without
  `--profile`, only the top-level settings apply, exactly as in a file without profiles.

#### Settings per CI event

Pull requests, deploys and scheduled runs often need different settings, most of all
where `finalize` publishes the state: a pull request must never replace production's. An
`on:` block holds settings for one event, applied over the top level and the selected
profile:

```yaml
finalize:
  files: [manifest]

on:
  pull-request:                 # pull/merge request runs
    finalize:
      artifacts-uri: gs://my-bucket/dbt-ci-prs/{pr}/   # a folder per pull request
  push:                         # pushes to the default branch
    finalize:
      artifacts-uri: gs://my-bucket/dbt-state/

profiles:
  prod:
    target: prod
    on:
      push:
        finalize:
          files: [manifest, cache]
```

A pull request usually only previews the commands that change production tables, while
`run` still builds its changes. The commands' own [`dry-run` keys](#sections) do that
without touching `run`:

```yaml
on:
  pull-request:
    delete:
      dry-run: true
    migration:
      dry-run: true
```

A top-level `dry-run: true` in the `pull-request` block would make `run` a dry run as well.

- Each event takes the same keys as the top level, in the same places. An event can't
  contain `profiles` or another `on:`. A profile can have its own `on:` block, applied after
  the top-level one.
- **`push` means a push to the default branch**, unless `push` lists its
  [`branches`](#deploy-branches). A push to any other branch, a tag, a manual run or a
  local run is no event, and only the settings outside `on:` apply. The default
  branch is `--base-ref` (`DBT_CI_BASE_REF`, `init.base-ref`, or the one `init` recorded)
  when set, else the CI system's own variable (see below), else what git's `origin/HEAD`
  points at.
- `{pr}` in `artifacts-uri` is the pull request's number, so pull requests don't
  overwrite each other's files (`gs://my-bucket/dbt-ci-prs/42/`); `{branch}` is its source
  branch with `/` and other characters that aren't letters, digits, `.`, `_` or `-` turned
  into `-`. A placeholder the run can't fill in fails `finalize`, which is why `{pr}` belongs
  under `pull-request:`. See [A folder per pull request](commands.md#a-folder-per-pull-request)
  for where the values come from, and a lifecycle rule that expires old pull request folders.
- **`schedule` means a scheduled run** (a nightly build, a drift check), whatever branch it
  runs on. See [Scheduled runs](#scheduled-runs).
- `--event pull-request|push|schedule|none` (or `DBT_CI_EVENT`) names the event yourself,
  for a CI system dbt-ci doesn't recognise or a manual run. `none` applies no event block.
- When the file has an `on:` block (or `--event` is given), `dbt-ci config show` prints
  the event, why it was chosen, and which block set each value,
  e.g. `Event: push (GitHub Actions push to the default branch 'main')` and a source of
  `event 'push'`.
- YAML 1.1 parsers read a bare `on:` key as `true`; dbt-ci reads it as `on`, so no quotes
  are needed.

**Preview a CI run before you push.** On your laptop no event is detected, so pass
`--event` to [`dbt-ci config show`](commands.md#config-show---show-resolved-settings) to
see exactly what a deploy or a pull request would run with. Nothing is executed. With the
file above:

```
$ dbt-ci config show finalize --profile prod --event push
Command:     dbt-ci finalize
Config file: dbt-ci.config.yaml
Profile:     prod (command line)
Event:       push (set with --event / DBT_CI_EVENT)

finalize options
OPTION           VALUE                      SOURCE
--artifacts-uri  gs://my-bucket/dbt-state/  event 'push'
--files          manifest, cache            profile 'prod', event 'push'

Common options
OPTION           VALUE                      SOURCE
--event          push                       command line
--profile        prod                       command line
--target         prod                       profile 'prod'

Defaults are hidden; pass --all to list every option.
```

The same command with `--event pull-request` shows the pull request writing to
`gs://my-bucket/dbt-ci-prs/` with only `manifest` (source `event 'pull-request'` and
`config file`), and `--event none` shows what a run outside both events gets. Pass the
same `--profile` and flags your CI step uses, and add `--json` before the command to
check a value in a script.

dbt-ci tells the events apart from the variables each CI system sets:

| CI system | Pull request | Push | Schedule | Default branch |
|---|---|---|---|---|
| GitHub Actions | `GITHUB_EVENT_NAME` is `pull_request`, `pull_request_target` or `merge_group` | `GITHUB_EVENT_NAME` is `push` (tags excluded) | `GITHUB_EVENT_NAME` is `schedule` | The event payload |
| GitLab CI | `CI_PIPELINE_SOURCE` is `merge_request_event` or `external_pull_request_event` | `CI_PIPELINE_SOURCE` is `push` | `CI_PIPELINE_SOURCE` is `schedule` | `CI_DEFAULT_BRANCH` |
| Azure Pipelines | `BUILD_REASON` is `PullRequest` | `BUILD_REASON` is `IndividualCI` or `BatchedCI` | `BUILD_REASON` is `Schedule` | `--base-ref` or git |
| Bitbucket Pipelines | `BITBUCKET_PR_ID` is set | Otherwise | `--event schedule` | `--base-ref` or git |
| CircleCI | `CIRCLE_PULL_REQUEST` is set | Otherwise | `--event schedule` | `--base-ref` or git |
| Buildkite | `BUILDKITE_PULL_REQUEST` is a number | `BUILDKITE_SOURCE` is `webhook` | `BUILDKITE_SOURCE` is `schedule` | `BUILDKITE_PIPELINE_DEFAULT_BRANCH` |
| Jenkins (multibranch) | `CHANGE_ID` is set | Otherwise | `--event schedule` | `--base-ref` or git |

On any other CI system the event is none unless `--event` names it. The same applies to
the commit `finalize` keeps a [per-commit copy](commands.md#finalize---finalize-state) for:
it comes from git, or from `GITHUB_SHA`, `CI_COMMIT_SHA`, `BUILDKITE_COMMIT` or
`CIRCLE_SHA1` without a usable checkout.

##### Deploy branches

Teams that deploy from more than the default branch, such as `main` plus `release/*`, or
staging from `develop`, list those branches under `push`:

```yaml
on:
  push:
    branches:
      - main
      - release/*
    finalize:
      artifacts-uri: gs://my-bucket/dbt-state/

profiles:
  staging:
    on:
      push:
        branches: develop       # replaces the top-level list for this profile
        target: staging
```

- A push counts when its branch matches **any** entry. The list replaces the default-branch
  rule rather than adding to it, so list the default branch too when it deploys. Without
  `branches`, only a push to the default branch counts, as before.
- Entries are branch names or [fnmatch](https://docs.python.org/3/library/fnmatch.html)
  patterns: `*` matches any run of characters **including `/`**, `?` one character and
  `[...]` one of a set. So `release/*` matches `release/1.2` and also
  `release/1.2/hotfix`, unlike a GitHub Actions branch filter, where `*` stops at `/`.
  Matching is case-sensitive and against the branch name without `refs/heads/`. A single
  branch can be written as a string, `branches: develop`.
- **Precedence:** the selected profile's `on.push.branches` replaces the top-level list as a
  whole; a profile without one uses the top-level list. Only the list is taken from the
  profile: once the run counts as a push, the top-level `push` settings still apply, then
  the profile's own, as for any event.
- With `branches`, the default branch is not needed, so a CI system that doesn't name it
  (Azure Pipelines, Bitbucket, CircleCI, Jenkins) detects the push without `--base-ref` or
  git's `origin/HEAD`, and `--base-ref` no longer decides which pushes count.
  `--event push` still applies the `push` block whatever the branch.
- `branches` is not a setting: it is never passed to a command. It is only allowed under
  `push`, at the top level or in a profile's `on:`; anywhere else, including under
  `pull-request`, is a validation error. `${VAR}` references are resolved, and a list
  that resolves to empty counts as not set.
- `dbt-ci config show` names the matching pattern, e.g.
  `Event: push (GitHub Actions push to 'release/1.2' (matches release/*))`, or
  `GitHub Actions push to 'feature/x', not one of the push branches (main, release/*)`
  when none matches.

> **Note:** `dbt-ci.config.yaml` is ignored by git by default (it is listed in `.gitignore`). Use it for local developer overrides and commit a `.example` variant for your team.

##### Scheduled runs

A nightly full build or drift check can take its own settings from `on: schedule:`:

```yaml
on:
  schedule:
    notifications:
      format: compact
```

```yaml
# .github/workflows/nightly.yml
on:
  schedule:
    - cron: "0 3 * * *"         # detected: GITHUB_EVENT_NAME is schedule
```

- Only the `schedule` block applies to a scheduled run, never `push`'s, even on the default
  branch. To publish state from a nightly build, give `schedule` its own
  `finalize.artifacts-uri`. The [pull request guard](commands.md#pull-requests-and-the-production-state)
  doesn't apply to schedules.
- Bitbucket Pipelines, CircleCI and Jenkins set no variable that marks a scheduled run
  (CircleCI only has the config-time pipeline values `pipeline.trigger.type` and
  `pipeline.schedule.name`, not an environment variable), so there a scheduled run reads
  as a push to its branch. Pass `--event schedule` (or set `DBT_CI_EVENT: schedule`) in the
  pipeline or job the schedule triggers.

### Core

| Flag | Aliases | Env Var(s) | Default | Description |
|------|---------|-----------|---------|-------------|
| `--dbt-project-dir` | | `DBT_PROJECT_DIR` | `.` | Path to the dbt project directory |
| `--profiles-dir` | | `DBT_PROFILES_DIR` | Auto-detect | Path to the directory containing `profiles.yml`. When unset, dbt-ci looks in the project directory, then the working directory, then `~/.dbt` |
| `--reference-state` | `--state` | `DBT_STATE` | `None` | Local path to the reference state directory (where `manifest.json` is stored) |
| `--target` | `-t` | `DBT_TARGET` | From `profiles.yml` | dbt target to use |
| `--vars` | `-v` | `DBT_VARS` | `""` | YAML string or path to a YAML file with dbt variables |
| `--defer` | | `DBT_DEFER`, `DEFER_FLAG` | `false` | Pass dbt's `--defer` flag (defers unmodified nodes to the production state). `DEFER_FLAG` is a fallback read only when `DBT_DEFER` is unset, and accepts `--defer`, `--no-defer`, an empty value or a boolean |
| `--runner` | `-r` | `DBT_RUNNER` | `dbt` | Runner to use: `dbt`, `local`, `docker`, `bash` |
| `--entrypoint` | | `DBT_ENTRYPOINT` | `dbt` | Command entrypoint for dbt |
| `--dbt-version` | | `DBT_VERSION` | Current | Pin a specific dbt version (e.g. `1.10.13`, or `2.0.9` for dbt v2). **Requires `--runner local`** |
| `--adapter` | `-a` | `DBT_ADAPTER` | `None` | dbt adapter to install (e.g. `dbt-bigquery`, `dbt-duckdb=1.10.0`). **Requires `--runner local`** |
| `--config` | `-c` | `DBT_CONFIG` | `dbt-ci.config.yaml` | Path to a dbt-ci YAML configuration file |
| `--profile` | | `DBT_CI_PROFILE` | Inherited from `init` | [Profile](#profiles) from the config file's `profiles` section to apply over its top-level settings |
| `--event` | | `DBT_CI_EVENT` | Detected | `pull-request`, `push`, `schedule` or `none`: which [`on:` block](#settings-per-ci-event) to apply. Detected from the CI system when not given |
| `--dry-run` | | `DBT_DRY_RUN` | `false` | Print commands without executing them (and without installing a pinned `--dbt-version`). In the config file, `delete`, `migration` and `ephemeral` read their own `dry-run` key before the top-level one; see [Sections](#sections) |
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
- `DBT_CI_CACHE_DIR` - Where the state cache and log file live (default: a directory per CI job, see [Cache Location](#cache-location))

**Note:** State management is cache-based. Run `init` once, then subsequent commands automatically use the cached state.

### Settings Inherited From `init`

`init` records the `--target`, `--vars`, `--state`, `--base-ref` and `--profile` it ran
with, and later commands reuse them, so they only need to be given once:

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

`init` writes its cache (state comparison, manifests, run report and log file) to a
cache directory, and later commands read it from there. Two jobs running at the same
time on one machine, such as two pull request jobs on a shared self-hosted runner, must
not share that directory, or they overwrite each other's state. dbt-ci therefore gives
each CI job its own directory automatically:

| Where dbt-ci runs | Cache directory |
|---|---|
| GitHub Actions | `$RUNNER_TEMP/dbt-ci` |
| Azure Pipelines | `$AGENT_TEMPDIRECTORY/dbt-ci` |
| GitLab CI, Buildkite, CircleCI, Bitbucket Pipelines | `<temp dir>/dbt-ci/<job id>` (from `CI_JOB_ID`, `BUILDKITE_JOB_ID`, `CIRCLE_WORKFLOW_JOB_ID` or `BITBUCKET_STEP_UUID`) |
| Anywhere else, e.g. your laptop | `<temp dir>/dbt-ci` |

On GitHub Actions and Azure Pipelines the runner cleans up the job's temp directory
itself. Everywhere else, every dbt-ci cache lives under `<temp dir>/dbt-ci`, so deleting
that one directory clears them all; don't do it while a job is running.

Set `DBT_CI_CACHE_DIR` to choose the directory yourself. It wins over the defaults
above, and is the way to isolate concurrent runs on other CI systems, e.g. Jenkins:

```bash
export DBT_CI_CACHE_DIR="/tmp/dbt-ci-${BUILD_TAG}"
dbt-ci init ...
dbt-ci run ...
```

All commands in the same CI job must see the same value, since that is how `run`,
`delete`, `ephemeral` and `finalize` find the cache written by `init`. This is also why
`init` and the commands after it must run in the same job.
