# Installation

[← dbt-ci](../README.md) · [GitHub Action](github-action.md) · **Installation** · [Commands](commands.md) · [Configuration](configuration.md) · [Runners](runners.md) · [State storage](state-storage.md) · [CI/CD examples](ci-examples.md)

## From PyPI (Recommended)

```bash
pip install dbt-ci
```

### Extras

The base install deliberately carries only dbt-core and the CLI plumbing. The cloud SDKs
and the Docker client are large and most projects need at most one of them, so they are
installed on demand:

| Extra | Installs | Needed for |
|-------|----------|------------|
| `gcp` | `google-cloud-bigquery`, `google-cloud-storage` | `gs://` state/artifact URIs, the BigQuery connector used by `delete`, `ephemeral destroy` and `migration` |
| `aws` | `boto3` | `s3://` state/artifact URIs |
| `docker` | `docker` | `--runner docker` |
| `all` | all of the above | |

```bash
pip install 'dbt-ci[gcp]'            # BigQuery + GCS
pip install 'dbt-ci[aws,docker]'     # S3 state, Docker runner
pip install 'dbt-ci[all]'            # everything
```

If a feature needs an extra you haven't installed, dbt-ci says which one and how to
install it rather than failing with an import traceback.

### Supported dbt versions

| dbt-core | Status |
|----------|--------|
| 1.10.x | Supported, tested in CI |
| 1.11.x | Supported, tested in CI |
| 1.12.x | Supported, tested in CI |

dbt-ci needs Python 3.12 or newer. CI tests Python 3.12 and 3.13 on every dbt-core version
above, and Python 3.14 on dbt-core 1.12, the first release that supports it.

`pip install dbt-ci` resolves the newest dbt-core 1.x (`>=1.10.13,<2.0.0`). To stay on an
older minor version, pin it alongside dbt-ci, e.g. `pip install dbt-ci 'dbt-core~=1.11.0'`.

The published Docker images are tagged per dbt-core version (`dbt-1.10.23`, `dbt-1.11.16`,
`dbt-1.12.6`); `latest` tracks the newest supported minor version.

## From GitHub

```bash
# Install from main branch
pip install git+https://github.com/datablock-dev/dbt-ci.git@main

# Install a specific version
pip install git+https://github.com/datablock-dev/dbt-ci.git@v1.0.0
```

## Local Development

```bash
git clone https://github.com/datablock-dev/dbt-ci.git
cd dbt-ci
pip install -e ".[dev]"
```

Or with pipenv:

```bash
pipenv install --dev
```

`pyproject.toml` is the single source of truth for dependencies — the `Pipfile` installs
the project itself rather than restating them, so the two cannot drift apart. Add or
change a dependency in `pyproject.toml`, then run `pipenv lock`.

After installation, the tool is available as `dbt-ci`.
