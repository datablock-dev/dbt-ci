import pytest
from typing import cast
from dbt_ci.schema import RunnerConfig


@pytest.fixture
def mock_runner_config():
    """
    Factory fixture that returns a RunnerConfig dict.
    Allows overriding default values by passing a dict.
    """

    default_config: RunnerConfig = {
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
        'dbt_version': None,
        'adapter': None,
        'docker_image': 'ghcr.io/dbt-labs/dbt-postgres:latest',
        'docker_platform': 'linux/amd64',
        'docker_volumes': [],
        'docker_env': [],
        'docker_network': 'host',
        'docker_user': None,
        'docker_args': '',
        'shell_path': '/bin/bash',
    }

    def _factory(overrides: dict | None = None) -> RunnerConfig:
        config = default_config.copy()

        if overrides:
            invalid_keys = set(overrides) - set(default_config)
            if invalid_keys:
                raise KeyError(
                    f"Invalid override keys: {invalid_keys}. "
                    f"Allowed keys: {set(default_config)}"
                )

            config.update(cast(RunnerConfig, overrides))

        return config

    return _factory
