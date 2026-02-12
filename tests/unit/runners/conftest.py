"""Shared fixtures for runner unit tests."""
import pytest
from src.schema import RunnerConfig


@pytest.fixture
def mock_runner_config() -> RunnerConfig:
    """Create a mock RunnerConfig for testing.
    
    This fixture can be overridden in individual tests by modifying
    the returned dictionary.
    """
    return {
        'runner': 'docker',
        'dbt_project_dir': '/workspace/dbt',
        'reference_state': '/workspace/dbt/.dbtstate',
        'profiles_dir': '/workspace/dbt',
        'target': 'dev',
        'vars': '',
        'entrypoint': 'dbt',
        'dry_run': False,
        'quiet': False,
        'log_level': 'INFO',
        'docker_image': 'ghcr.io/dbt-labs/dbt-postgres:latest',
        'docker_platform': 'linux/amd64',
        'docker_volumes': [],
        'docker_env': [],
        'docker_network': 'host',
        'docker_user': None,
        'docker_args': '',
        'shell_path': '/bin/bash',
    }
