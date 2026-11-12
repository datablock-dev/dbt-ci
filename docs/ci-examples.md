# CI/CD Examples

[← dbt-ci](../README.md) · [GitHub Action](github-action.md) · [Installation](installation.md) · [Commands](commands.md) · [Configuration](configuration.md) · [Runners](runners.md) · [State storage](state-storage.md) · **CI/CD examples**

## GitHub Actions

Use the [GitHub Action](github-action.md). To call the CLI yourself instead:

```yaml
name: dbt CI

on: [pull_request]

jobs:
  dbt-ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v7
        with:
          python-version: '3.12'

      # Authenticate to GCP here, e.g. with google-github-actions/auth

      - name: Install dbt-ci
        # The gcp extra provides the GCS client needed for the gs:// state URI below
        run: pip install 'dbt-ci[gcp]' dbt-bigquery

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

## A reusable workflow with profiles

A reusable workflow that serves several targets tends to pass the same flags to every
step, with `||` fallbacks for empty inputs:

```yaml
- run: |
    dbt-ci init \
      --reference-target ${{ inputs.reference-target || inputs.target }} \
      --reference-vars '${{ inputs.reference-vars || inputs.vars }}' \
      --target ${{ inputs.target }} \
      --vars '${{ inputs.vars }}' \
      --state-uri gs://${{ env.DBT_STATE_BUCKET }}/manifest.json
- if: ${{ inputs.target == 'action' }}
  run: dbt-ci ephemeral --target ${{ inputs.target }} --vars '${{ inputs.vars }}'
- run: dbt-ci delete --target ${{ inputs.target }} --vars '${{ inputs.vars }}' ${{ env.DRY_RUN }}
```

With [profiles](configuration.md#profiles), what differs per target moves into the config
file, the workflow picks a profile once, and each step shrinks to the command itself.

### 1. Put the settings in `dbt-ci.config.yaml`

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/datablock-dev/dbt-ci/main/dbt-ci.config.schema.json
project-dir: dbt
profiles-dir: dbt

notifications:
  provider: slack
  pr-comment: true            # dbt-ci report also comments on the pull request

# Shared by every profile
init:
  reference-target: prod
  comparison-strategy: hybrid
  compare-to: auto            # only the PR's own changes, not what main gained since
  state-uri: gs://${DBT_STATE_BUCKET}/dbt-state/manifest.json

run:
  exclude:
    - tag:ci_skip             # heavy or slow models stay out of CI

profiles:
  # Pull requests: build the changes in an ephemeral environment
  action:
    target: action
    vars: '{use_production_data: false}'
    defer: true
    init:
      reference-vars: '{use_production_data: true}'

  # Deploys on main: build in production and publish the new state
  prod:
    target: prod
    run:
      exclude: []             # build everything in production
    finalize:
      artifacts-uri: gs://${DBT_STATE_BUCKET}/dbt-state/
```

- `${DBT_STATE_BUCKET}` is read from the environment when the file loads, so the bucket
  can still come from the workflow.
- `vars` and `reference-vars` are YAML strings, exactly as you would pass them to `--vars`.
- A profile's lists replace the top-level ones, so `exclude: []` in `prod` builds the
  models the pull requests skipped.
- `compare-to: auto` compares a pull request with its merge base, so changes merged into
  `main` after the branch was created don't count as the PR's own. `finalize` keeps a copy
  of each deployed manifest under `dbt-state/<commit>/` for this; see
  [Comparing against the merge base](commands.md#comparing-against-the-merge-base).
  A deploy on `main` itself compares with the latest state.
- Instead of a profile per target, settings can also follow the CI event: an
  [`on:` block](configuration.md#settings-per-ci-event) with `pull-request:` and `push:`
  (pushes to the default branch) is detected on GitHub Actions, GitLab CI, Azure
  Pipelines, Bitbucket, CircleCI, Buildkite and Jenkins, and `schedule:` covers scheduled
  runs. A pull request is never allowed to publish over the production state.

### 2. Select the profile in the workflow

```yaml
name: dbt-ci

on:
  workflow_call:
    inputs:
      target:
        description: Profile in dbt-ci.config.yaml (action or prod)
        type: string
        required: true
      run-delete:
        type: boolean
        default: false

jobs:
  dbt-ci:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write          # for google-github-actions/auth
      pull-requests: write     # for the PR comment
    env:
      DBT_CI_PROFILE: ${{ inputs.target }}
      DBT_STATE_BUCKET: my-dbt-state
      # Pull requests only preview what they would change in production
      DRY_RUN: ${{ github.event_name == 'pull_request' && '--dry-run' || '' }}
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0       # dbt-ci deepens a shallow clone itself, but this saves the fetch

      - uses: actions/setup-python@v7
        with:
          python-version: '3.12'

      # Authenticate to GCP here, e.g. with google-github-actions/auth

      - run: pip install 'dbt-ci[gcp]' dbt-bigquery

      - name: Show the dbt-ci settings
        run: dbt-ci config show init

      - name: Initialize dbt-ci state
        env:
          SLACK_WEBHOOK_URL: ${{ secrets.DBT_CI_SLACK_WEBHOOK_URL }}
        run: dbt-ci init

      - name: Set up the ephemeral environment
        if: ${{ inputs.target == 'action' }}
        run: dbt-ci ephemeral create

      - name: Migrate partitions
        run: dbt-ci migration ${{ inputs.target != 'action' && env.DRY_RUN || '' }}

      - name: Build and test the changes
        run: dbt-ci run

      - name: Delete removed models
        if: ${{ inputs.run-delete }}
        run: dbt-ci delete ${{ env.DRY_RUN }}

      - name: Report
        if: ${{ always() }}
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: dbt-ci report

      - name: Tear down the ephemeral environment
        if: ${{ always() && inputs.target == 'action' }}
        run: dbt-ci ephemeral destroy

      - name: Publish the production state
        if: ${{ inputs.target == 'prod' }}
        run: dbt-ci finalize
```

Callers pick the profile and nothing else:

```yaml
# .github/workflows/pr.yml
on: pull_request
jobs:
  dbt-ci:
    uses: my-org/workflows/.github/workflows/dbt-ci.yml@main
    with:
      target: action
    secrets: inherit
```

- `DBT_CI_PROFILE` selects the profile for every step. `init` records it, together with
  the target, vars and state it ran with, so the later commands need no flags at all.
- `DRY_RUN` stays a flag on the steps that change production, because whether to preview
  depends on the event, not on the profile. Empty flags are ignored, so
  `${{ env.DRY_RUN }}` on a deploy simply runs for real.
- The Slack webhook and `GITHUB_TOKEN` stay secrets in the workflow; the config file only
  says where to post.
- To change a setting for one repository, pass the flag in that step (a flag wins over
  the profile) or add a profile to its `dbt-ci.config.yaml`.

### 3. Check what a step will run with

`dbt-ci config show` prints each setting a command would use and where it came from,
without running anything. The *Show the dbt-ci settings* step above puts that at the top
of every job log; locally, pass the profile you are debugging:

```bash
$ DBT_STATE_BUCKET=my-dbt-state dbt-ci config show run --profile action
Command:     dbt-ci run
Config file: dbt-ci.config.yaml
Profile:     action (command line)

run options
OPTION                    VALUE                         SOURCE
--exclude                 tag:ci_skip                   config file

Common options
OPTION                    VALUE                         SOURCE
--dbt-project-dir         dbt                           config file
--defer                   true                          profile 'action'
--notifications-provider  slack                         config file
--profile                 action                        command line
--profiles-dir            dbt                           config file
--target                  action                        profile 'action'
--vars                    {use_production_data: false}  profile 'action'

Defaults are hidden; pass --all to list every option.
```

After `init` has run, `config show` also lists the settings later commands inherit from
it. Add `--json` to check a value in a script, e.g. that a deploy really targets `prod`:

```bash
dbt-ci config show --json run \
  | jq -e '.settings[] | select(.option == "--target") | .value == "prod"'
```

## GitLab CI Example

```yaml
dbt-ci:
  image: python:3.12
  script:
    - pip install 'dbt-ci[gcp]' dbt-bigquery
    - dbt-ci init --dbt-project-dir dbt --state-uri gs://my-dbt-state/prod/manifest.json --reference-target production --state dbt/.dbtstate
    - dbt-ci run --mode models
  only:
    - merge_requests
```

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
Create an ephemeral test environment, and tear it down at the end of the job:
```bash
dbt-ci ephemeral create --target ci
dbt-ci ephemeral destroy
```
