# Commands

[← dbt-ci](../README.md) · [GitHub Action](github-action.md) · [Installation](installation.md) · **Commands** · [Configuration](configuration.md) · [Runners](runners.md) · [State storage](state-storage.md) · [CI/CD examples](ci-examples.md)

All commands share a set of **common options** (see [Common Options](configuration.md#common-options)). Command-specific flags are listed under each command.

---

## `init` - Initialize State

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
| `--reference-path` | | `DBT_REFERENCE_PATH` | `reference` | **Deprecated — no effect.** The reference compile writes to dbt's own target path |
| `--reference-vars` | `--ref-vars` | `DBT_REFERENCE_VARS` | `None` | Variables to pass to dbt when compiling the reference manifest (YAML string or file path) |
| `--state-uri` | | `DBT_STATE_URI`, `STATE_URI` | `None` | Remote URI for the state manifest (e.g. `gs://bucket/manifest.json`, `s3://bucket/manifest.json`) |
| `--target-compile` | | `DBT_TARGET_COMPILE` | `false` | Run the second compile pass against the actual target |
| `--skip-reference-compile` | | `DBT_SKIP_REFERENCE_COMPILE` | `false` | Skip the compile pass against the reference/production state |
| `--comparison-strategy` | `--comparison` | `DBT_COMPARISON_STRATEGY` | `hybrid` | Strategy for detecting changed nodes: `dbt`, `git`, or `hybrid` |
| `--base-ref` | | `DBT_CI_BASE_REF` | Auto-detected | Base branch to diff against (e.g. `main`). Auto-detected from `GITHUB_BASE_REF` or git if not set |

> All [common options](configuration.md#common-options) also apply.

**Git comparison and clone depth:** the `git` and `hybrid` strategies diff `origin/<base-ref>...HEAD` — the merge base — so only the commits on your branch count as changes. Shallow clones often don't contain the merge base; dbt-ci falls back to a direct diff and logs a debug message when that happens. For an accurate change set, fetch full history (`actions/checkout` with `fetch-depth: 0`).

How git's file-level changes are mapped to nodes:

- **Moved or renamed files** are reported by git as a delete of the old path plus an add of the new one. dbt identifies nodes by `unique_id`, which a move does not change, so a node that still exists in the target manifest is treated as **modified**, not deleted and re-added. Only nodes that are really gone are reported as deleted (and dropped by `delete`).
- **Macro changes** select every node that calls the changed macro, directly or through another macro.
- **YAML-only changes** (config, contracts, columns in a `schema.yml`) select the model the YAML configures. With `git`, every model configured by a changed YAML file is selected; with `hybrid`, only those that dbt also flags as modified.
- **`--dbt-project-dir`** is matched as a directory relative to the repository root, so `dbt`, `./dbt`, `dbt/` and an absolute path behave the same, and files in look-alike folders such as `analytics_dbt/` are ignored.

---

## `run` - Run Modified Models

Detects and runs models that have changed. Uses cached state from `init`, and fails if `init` has not run.

```bash
dbt-ci run --dbt-project-dir dbt --mode models
```

**Flags:**

| Flag | Aliases | Env Var(s) | Default | Description |
|------|---------|-----------|---------|-------------|
| `--mode` | `-m`, `--nodes`, `-n` | `DBT_NODES` | `all` | What to run: `all`, `models`, `seeds`, `snapshots`, `tests` |
| `--downstream-depth` | | `DBT_DOWNSTREAM_DEPTH` | Full graph | How many levels of downstream dependencies to include (dbt's `model+N`) |
| `--filters` | `-f` | | `None` | Extra resource-type filter (repeatable, choices: `models`, `seeds`, `snapshots`, `tests`). E.g. `--mode tests -f snapshots` to run only tests that have a snapshot dependency |

With `--mode all`, the steps run in dependency order: **seeds → snapshots → models → tests**, so models built on a changed snapshot read its new state and tests run once everything they check exists. The test step runs both data tests and dbt unit tests (dbt ≥ 1.8).

### Limiting blast radius

By default a change selects its **entire** downstream graph. On a large project a change
to a core staging model therefore rebuilds almost everything, which is the opposite of
what change-based CI is for. `--downstream-depth` caps how far a change propagates:

```bash
dbt-ci run --downstream-depth 0   # only what changed
dbt-ci run --downstream-depth 1   # changed models and their direct children
dbt-ci run --downstream-depth 2   # two levels out
dbt-ci run                        # unlimited (default)
```

For a chain `customers → l1 → l2 → l3` where only `customers` changed:

| Flag | Models run |
|------|------------|
| `--downstream-depth 0` | `customers` |
| `--downstream-depth 1` | `customers`, `l1` |
| `--downstream-depth 2` | `customers`, `l1`, `l2` |
| *(omitted)* | `customers`, `l1`, `l2`, `l3` |

New and deleted nodes are always included regardless of depth — a new model has to run
whether or not anything depends on it yet. Every seed, snapshot and model the run builds
also gets its data and unit tests, even though a test sits one level below the node it
checks.

Deleted nodes no longer exist in the target manifest, so `run` does not look for their
downstream nodes there. A node that depended on a deleted one has changed itself (its `ref`
or test arguments differ) and is picked up as modified or new. This also covers generic
tests whose arguments changed: dbt gives them a new `unique_id`, so they show up as one
deleted and one new test.

> All [common options](configuration.md#common-options) also apply.

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

## `ephemeral` - Ephemeral Environment

`ephemeral` has two subcommands: `create` builds the environment and `destroy` tears it
down. Plain `dbt-ci ephemeral` (no subcommand) still means `create`, so existing pipelines
keep working. Options go after the subcommand (`dbt-ci ephemeral destroy --target ci`).

### `ephemeral create`

Clones changed models and their downstream dependencies into an isolated target schema using **`dbt clone`**, allowing integration testing without affecting production. Uses cached state from `init`.

> **Important:** `--target` and `--vars` must match the environment you want to clone into. The clone operation reads your `profiles.yml` to determine the target database/schema — if these are wrong, models will be cloned to the wrong location or the command will fail.

```bash
dbt-ci ephemeral create \
  --target my-pr-env \
  --vars '{"use_production_data":"false"}'
```

**How it works:**
1. Reads the cached change set from `init`
2. Builds a selection of all affected models, their direct parents and their downstream dependencies. Seeds that `run` builds itself are excluded, so `dbt seed` never lands on a cloned view
3. Runs `dbt clone --select <nodes>` targeting the specified environment
4. The cloned tables/views can then be used as the base for subsequent `dbt run` commands in the PR environment
5. Records the datasets it cloned into, as dbt resolved them for the target it cloned into, so `ephemeral destroy` can drop them later

If `dbt clone` fails, `ephemeral` exits with a non-zero code on every runner.

**Flags:**

| Flag | Aliases | Env Var(s) | Default | Description |
|------|---------|-----------|---------|-------------|
| `--keep-env` | | `DBT_KEEP_ENV` | `false` | **Deprecated — no effect.** Creating the environment never destroys it; use `ephemeral destroy` to tear it down |

> All [common options](configuration.md#common-options) also apply.

### `ephemeral destroy`

Drops the schemas (datasets) that `ephemeral create` cloned into, on any adapter (see
[How dbt-ci drops relations](#how-dbt-ci-drops-relations)). Schemas used by any node in
the reference (production) manifest are never dropped, and a failed teardown fails the
step.

```yaml
- name: Tear down ephemeral environment
  if: ${{ always() }}
  run: dbt-ci ephemeral destroy
```

- Run it in the **same job** as `ephemeral create`: the list of cloned datasets lives in
  the dbt-ci cache (see [Cache Location](configuration.md#cache-location)).
- Use `if: always()` so a failed `run` step doesn't leave the datasets behind.
- It doesn't upload anything or clear the cache, so it can run before or after `finalize`,
  and a failed teardown can be retried by running it again.
- `--target` defaults to the one `init` recorded. With `--dry-run` it only lists the
  datasets it would drop.

> All [common options](configuration.md#common-options) also apply.

---

## `delete` - Delete Removed Models

Detects and deletes models that have been removed from the project. Uses cached state from `init`.

```bash
dbt-ci delete --dry-run  # preview what will be deleted
dbt-ci delete            # execute deletions
```

The tables dropped are the ones in the **reference** manifest (usually production), so run the real delete only after the removal is merged, and use `--dry-run` everywhere else.

A node is only dropped if it is really gone from the current project. Nodes that still exist in the target manifest (for example a model whose file was moved or renamed, which git reports as delete + add) are skipped, as are relations that another target node still builds (for example through an `alias`). `delete` fails if `init` has not run, instead of passing without doing anything. The connection comes from the `profile` named in `dbt_project.yml` and the `--target` output in `profiles.yml`; see [How dbt-ci drops relations](#how-dbt-ci-drops-relations).

### How dbt-ci drops relations

`delete` and `ephemeral destroy` work on every dbt adapter:

- **BigQuery** uses dbt-ci's native connector (`pip install 'dbt-ci[gcp]'`), as before.
- **Every other adapter** (Snowflake, Databricks, Redshift, Postgres, DuckDB, ...) drops
  through dbt itself, with `dbt run-operation` and the adapter's own `get_drop_sql` and
  `drop_schema` macros. The DDL is therefore exactly what dbt would run for that adapter
  (`DROP TABLE` or `DROP VIEW`, `CASCADE`, quoting), and dbt-ci needs no warehouse SDK.

`run-operation` only runs macros that belong to a project, so dbt-ci writes a small helper
project to `<dbt-project-dir>/target/dbt_ci_operations` that holds its macros and uses
your profile. Your own project is not modified, and the helper ignores itself in git. It
runs through the same runner as every other dbt command; with `--runner docker`, the
dbt project directory has to be mounted with `--docker-volumes` (or located with
`DBT_PROJECT_DIR` in `--docker-env`).

Relations that no longer exist are skipped, so a teardown or delete can be re-run safely.

**Flags:**

> Only [common options](configuration.md#common-options) apply — no command-specific flags.

---

## `migration` - Migrate Partitioning Changes

Detects models whose partitioning configuration changed between the reference and target
state, and rebuilds the affected tables with the new partitioning spec. Uses cached state
from `init`.

BigQuery cannot change a table's partitioning in place, so each affected table is copied
into a temporary table with the new spec (keeping the model's `cluster_by`,
`require_partition_filter` and `partition_expiration_days`). The original is then renamed
to `<table>__dbt_ci_backup`, the copy is renamed into place, and only then is the backup
dropped — if the swap fails, the original data is still in the backup table. The table
migrated is the relation dbt resolves for the model, including its `alias`. Only **incremental** models are considered — other materializations are
rebuilt by dbt anyway.

```bash
dbt-ci migration --dry-run  # list the tables that would be rebuilt
dbt-ci migration            # apply the changes
```

> **Warning:** this rewrites tables in place. Always review the `--dry-run` output first.
> Requires a connector implementing a migration strategy — currently BigQuery only.

**Flags:**

> Only [common options](configuration.md#common-options) apply — no command-specific flags.

---

## `report` - Summarise the Run

Renders the change set detected by `init` and the status of every command that has run
so far. In GitHub Actions the report is appended to the job summary automatically, so no
workflow wiring is needed beyond calling it. Each command's entry ends as `completed` or
`failed` however it exits, including dry runs and runs with nothing to do.

```bash
dbt-ci report                       # → $GITHUB_STEP_SUMMARY, or stdout locally
dbt-ci report --output report.md    # → a file
dbt-ci report --format json         # → machine-readable
dbt-ci report --pr-comment          # → also posted as a comment on the pull request
```

The report covers:

- **Change counts and node names**, grouped as modified / new / deleted. Long lists fold
  into a collapsible block.
- **Exposure impact** — the exposures downstream of the change set, including those
  downstream of *deleted* nodes, which is usually the case worth catching.
- **Command status and duration** for each of `init`, `run`, `delete`, `ephemeral` and
  `migration` that has run.

**Flags:**

| Flag | Aliases | Env Var(s) | Default | Description |
|------|---------|-----------|---------|-------------|
| `--output` | `-o` | `DBT_REPORT_OUTPUT` | `$GITHUB_STEP_SUMMARY` or stdout | Where to write the report |
| `--format` | `-F` | `DBT_REPORT_FORMAT` | `markdown` | `markdown` or `json` |
| `--pr-comment` / `--no-pr-comment` | | `DBT_NOTIFICATIONS_PR_COMMENT` | `false` | Also post the report as a comment on the GitHub pull request (`notifications.pr-comment` in the config file) |

> All [common options](configuration.md#common-options) also apply.

### Posting the report as a PR comment

With `--pr-comment` (or `notifications.pr-comment: true`), `report` also posts the
markdown report as a comment on the pull request. dbt-ci owns a single comment per pull
request and edits it on every later run instead of adding new ones. The comment is always
markdown, even with `--format json`.

The step needs a token that can write pull request comments:

```yaml
permissions:
  pull-requests: write

steps:
  - run: dbt-ci report --pr-comment
    env:
      GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

The pull request is detected from the GitHub Actions event, and GitHub Enterprise works
through `GITHUB_API_URL`. Posting the comment never fails the job: on a run that is not
for a pull request, without a token, or when GitHub rejects the request (pull requests
from forks get a read-only token), `report` logs why and carries on. Reports longer than
GitHub's 65,536-character comment limit are cut, with a note pointing to the job summary.

---

## `config` - Generate a Config File

Writes a commented `dbt-ci.config.yaml` skeleton with the common options pre-filled, so
you don't have to memorise every flag. See [Configuration File](configuration.md#configuration-file).

```bash
dbt-ci config                          # create ./dbt-ci.config.yaml
dbt-ci config --output dbt/dbt-ci.config.yaml
dbt-ci config --force                  # overwrite an existing file
```

**Flags:**

| Flag | Aliases | Default | Description |
|------|---------|---------|-------------|
| `--output` | `-o` | `dbt-ci.config.yaml` | Destination path for the generated file |
| `--force` | `-f` | `false` | Overwrite the file if it already exists |

> This command does not take the [common options](configuration.md#common-options).

---

## `finalize` - Finalize State

Run after `run`, `delete`, or `ephemeral` to upload artifacts and clean up the local cache for the next CI run.

```bash
dbt-ci finalize
dbt-ci finalize --artifacts-uri s3://my-bucket/dbt-artifacts/
```

**Flags:**

| Flag | Aliases | Env Var(s) | Default | Description |
|------|---------|-----------|---------|-------------|
| `--artifacts-uri` | | `DBT_ARTIFACTS_URI`, `ARTIFACTS_URI` | `None` | Object storage URI for uploading run artifacts such as the updated `manifest.json` (e.g. `s3://bucket/dbt-artifacts/`) |
| `--files` | | `DBT_FINALIZE_FILES` | `manifest` | Which artifacts to upload (repeatable): `manifest`, `cache`, `log` |
| `--clean-ephemeral` | `--destroy-ephemeral` | `DBT_CLEAN_EPHEMERAL`, `DBT_DESTROY_EPHEMERAL` | `false` | **Deprecated — use [`ephemeral destroy`](#ephemeral-destroy).** Drop the datasets that `ephemeral` cloned into, the same way `ephemeral destroy` does |

Uploaded artifacts land at `<artifacts-uri>/manifest.json`, `<artifacts-uri>/cache.json`
and `<artifacts-uri>/logs.txt` respectively (a trailing `/` on the URI is ignored).
With `--dry-run`, nothing is uploaded, the cache is kept, and `--clean-ephemeral` only
lists the datasets it would drop. `log` uploads the run log that dbt-ci writes
to `<cache dir>/dbt-ci.log`.

`--clean-ephemeral` runs before the upload, so a missing manifest or a failed upload
doesn't leave the CI datasets behind. If the cleanup itself fails, the artifacts are
still uploaded, the step fails, and the cache is kept so a re-run can retry the cleanup.

> **Note:** the log file always records at `DEBUG` level, including the resolved
> configuration for each command. Values whose names look sensitive (webhook, token,
> password, secret, credential, api_key) are masked before being written, so uploading
> the log does not publish your Slack webhook or credentials passed via `--docker-env`.
> This is a name-based heuristic — review your artifact bucket's access controls before
> enabling `--files log`.

> All [common options](configuration.md#common-options) also apply.
