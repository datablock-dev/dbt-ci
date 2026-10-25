# GitHub Action

[← dbt-ci](../README.md) · **GitHub Action** · [Installation](installation.md) · [Commands](commands.md) · [Configuration](configuration.md) · [Runners](runners.md) · [State storage](state-storage.md) · [CI/CD examples](ci-examples.md)

The quickest way to use dbt-ci is the GitHub Action. It installs dbt-ci and your dbt
adapter, builds and tests only what the pull request changed, and comments the impact on
the pull request:

```yaml
name: dbt CI

on:
  pull_request:

permissions:
  contents: read
  pull-requests: write   # for the PR comment

jobs:
  dbt-ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0   # the git comparison diffs against the merge base

      # Authenticate to your warehouse and state bucket here
      # (e.g. google-github-actions/auth or aws-actions/configure-aws-credentials)

      - uses: datablock-dev/dbt-ci@v1
        with:
          project-dir: dbt
          profiles-dir: dbt
          target: ci
          state-uri: gs://my-bucket/dbt-state/manifest.json
          reference-target: production
          extras: gcp
          adapter: dbt-bigquery
```

By default the action runs `init`, `run` and `report`: it detects the changed nodes,
builds them and their downstream dependents, writes the [report](commands.md#report---summarise-the-run)
to the job summary and posts it as a single pull request comment that is updated on every
push. The reference manifest at `state-uri` is the one your production deploy produced
(upload its `target/manifest.json` after `dbt build`, or use
[`finalize --artifacts-uri`](commands.md#finalize---finalize-state)).

## Choosing the commands

`commands` takes one dbt-ci command per line, run in order. A line can carry extra flags,
which win over the inputs. After a failure the remaining commands are skipped, except
`report` and `ephemeral destroy`, so the report explains the failure and the ephemeral
environment is always torn down:

```yaml
      - uses: datablock-dev/dbt-ci@v1
        with:
          target: ci
          state-uri: gs://my-bucket/dbt-state/manifest.json
          reference-target: production
          extras: gcp
          adapter: dbt-bigquery
          commands: |
            init
            ephemeral create
            run --downstream-depth 1
            delete --dry-run
            report
            ephemeral destroy
```

## Using the outputs

```yaml
      - uses: datablock-dev/dbt-ci@v1
        id: dbt
        with:
          # ...

      - name: Only when the PR changes dbt nodes
        if: steps.dbt.outputs.has-changes == 'true'
        run: echo "${{ steps.dbt.outputs.modified }} modified, ${{ steps.dbt.outputs.new }} new"
```

dbt-ci stays on `PATH` for later steps of the job, and `DBT_CI_CACHE_DIR` points them at
the cache `init` wrote, so a later step can run `dbt-ci ephemeral destroy` or `dbt` itself.

## Inputs

Inputs are passed to dbt-ci as flags, so they win over `dbt-ci.config.yaml`. Inputs left
empty pass nothing, so the config file (found in the working directory or the
`project-dir`) and dbt-ci's defaults still apply.

| Input | Default | Description |
|-------|---------|-------------|
| `commands` | `init`, `run`, `report` | dbt-ci commands to run, one per line |
| `working-directory` | `.` | Directory to run dbt-ci from (the root of the git checkout) |
| `project-dir` | | `--dbt-project-dir` |
| `profiles-dir` | | `--profiles-dir` |
| `target` | | `--target` |
| `vars` | | `--vars` |
| `state` | | `--state` |
| `config` | | `--config` |
| `runner` | | `--runner` (`dbt`, `local`, `docker`, `bash`) |
| `defer` | `false` | `--defer` |
| `log-level` | | `--log-level` |
| `dry-run` | `false` | `--dry-run` |
| `state-uri` | | `init --state-uri` |
| `reference-target` | | `init --reference-target` |
| `comparison-strategy` | | `init --comparison-strategy` (`hybrid`, `git`, `dbt`) |
| `base-ref` | PR base branch | `init --base-ref` |
| `mode` | | `run --mode` |
| `downstream-depth` | | `run --downstream-depth` |
| `artifacts-uri` | | `finalize --artifacts-uri` |
| `pr-comment` | `true` | `report --pr-comment`; `false` passes `--no-pr-comment` |
| `github-token` | `${{ github.token }}` | Token used for the PR comment |
| `slack-webhook` | | Slack webhook; `init` posts a summary of the change set |
| `install` | `true` | Install dbt-ci into a virtual environment; `false` uses the `dbt-ci` on `PATH` |
| `version` | the action's version | dbt-ci version to install from PyPI, or `latest` |
| `extras` | | dbt-ci [extras](installation.md#extras), comma-separated (`gcp`, `aws`, `docker`) |
| `adapter` | | pip requirements for your dbt adapter, space-separated, e.g. `dbt-snowflake~=1.11.0`. Needed with the default `dbt` runner |
| `python-version` | `3.12` | Python for dbt-ci's virtual environment. The job's own Python is left untouched |

## Outputs

| Output | Description |
|--------|-------------|
| `modified` | Number of modified nodes |
| `new` | Number of new nodes |
| `deleted` | Number of deleted nodes |
| `has-changes` | `true` when any node was modified, added or deleted |
| `report-json` | Path to the JSON report (`dbt-ci report --format json`) |

The outputs are empty when `init` did not run or failed.

## Versions and runners

- `@v1` follows the latest 1.x release; pin an exact release with e.g. `@v1.10.0`.
  Each release is tested by running the action against a DuckDB project in CI.
- The action runs on Linux and macOS runners, GitHub-hosted or self-hosted. Each job gets
  its own dbt-ci cache under `RUNNER_TEMP`, so concurrent jobs on one self-hosted runner
  don't overwrite each other's state.
- With a shallow checkout (the `actions/checkout` default), the action warns that the git
  comparison may not find the merge base. Use `fetch-depth: 0`, or
  `comparison-strategy: dbt`.
