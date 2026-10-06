# Test Structure

This directory contains tests for dbt-ci organized into two categories:

## Unit Tests (`unit/`)

Unit tests focus on testing individual components and functions in isolation:

- **Utilities**: Test helper functions in `src/utilities/`
- **Parsers**: Test manifest parsing and graph generation
- **Variables**: Test configuration resolution and validation
- **Connectors**: Test database and cloud storage connectors
- **Runners**: Mock runner execution and command building

**Run unit tests:**
```bash
pytest tests/unit/
```

**Example structure:**
```
tests/unit/
├── test_utilities.py
├── test_parser.py
├── test_variables.py
├── test_dependency_graph.py
└── connectors/
    ├── test_bigquery.py
    └── test_storage.py
```

## End-to-End Tests (`e2e/`)

End-to-end tests validate complete workflows and integration scenarios:

- **Initialization**: Test `dbt-ci init` command flow
- **Run workflows**: Test `dbt-ci run` with different modes
- **State comparison**: Test modified node detection
- **Runner integration**: Test actual dbt execution with different runners
- **Cloud storage**: Test S3 state upload/download

**Run e2e tests:**
```bash
pytest tests/e2e/
```

`test_dbt_versions.py` runs `dbt-ci init` and `dbt-ci run` against a real dbt binary and
is skipped unless `DBT_CI_E2E_DBT_BINARY` points at one that can run DuckDB. CI uses it to
cover dbt v2:

```bash
python -m venv /tmp/dbt-v2 && /tmp/dbt-v2/bin/pip install "dbt==2.0.6"
DBT_CI_E2E_DBT_BINARY=/tmp/dbt-v2/bin/dbt pytest tests/e2e/test_dbt_versions.py
```

**Example structure:**
```
tests/e2e/
├── test_init_workflow.py
├── test_run_workflow.py
├── test_ephemeral_workflow.py
├── test_delete_workflow.py
└── test_cloud_storage.py
```

## Running Tests

**All tests:**
```bash
pytest tests/
```

**Specific category:**
```bash
pytest tests/unit/
pytest tests/e2e/
```

**With coverage:**
```bash
pytest tests/ --cov=src --cov-report=html
```

**Verbose output:**
```bash
pytest tests/ -v
```

## Test Dependencies

Install test dependencies:
```bash
pip install pytest pytest-cov pytest-mock
```

Or if using the project:
```bash
pip install -e ".[dev]"
```
