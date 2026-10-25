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
