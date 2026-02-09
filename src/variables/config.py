"""Shared configuration for CLI options and environment variables."""

# Configuration mapping: defines all options with their metadata
from typing import Dict, Optional
from src.schema import DependencyGraphNodeType, RunModes


OPTIONS_CONFIG = {
    'nodes': {
        'env_vars': ['DBT_NODES'],
        'cli_flags': ['nodes'],
        'required': False,
        'default': 'all',
        'choices': ['all', 'models', 'seeds', 'snapshots', 'tests'],
        'help': 'Run mode for dbt-ci (default: all)'
    },
    'prod_manifest_dir': {
        'env_vars': ['DBT_STATE', 'DBT_STATE_DIR', 'STATE_DIR'],
        'cli_flags': ['prod_manifest_dir', 'reference_manifest_dir', 'state'],
        'required': True,
        'default': None,
        'help': 'Path to the production/reference manifest.json directory'
    },
    'dbt_project_dir': {
        'env_vars': ['DBT_PROJECT_DIR'],
        'cli_flags': ['dbt_project_dir'],
        'required': False,
        'default': '.',
        'help': 'Path to the dbt project directory'
    },
    'profiles_dir': {
        'env_vars': ['DBT_PROFILES_DIR'],
        'cli_flags': ['profiles_dir'],
        'required': False,
        'default': None,
        'help': 'Path to the directory containing the dbt profiles.yml file'
    },
    'production_target': {
        'env_vars': ['DBT_PRODUCTION_TARGET'],
        'cli_flags': ['production_target'],
        'required': False,
        'default': None,
        'help': 'The dbt target to use for production/reference manifest (defaults to default)'
    },
    'target': {
        'env_vars': ['DBT_TARGET'],
        'cli_flags': ['target'],
        'required': False,
        'default': None,
        'help': 'The dbt target to use'
    },
    'vars': {
        'env_vars': ['DBT_VARS'],
        'cli_flags': ['vars'],
        'required': False,
        'default': '',
        'help': 'YAML string or path to YAML file with variables'
    },
    'runner': {
        'env_vars': ['DBT_RUNNER'],
        'cli_flags': ['runner'],
        'required': False,
        'default': 'dbt',
        'choices': ['local', 'docker', 'bash', 'dbt'],
        'help': 'Runner to use for executing dbt commands'
    },
    'entrypoint': {
        'env_vars': ['DBT_ENTRYPOINT'],
        'cli_flags': ['entrypoint'],
        'required': False,
        'default': 'dbt',
        'help': 'Command entrypoint for dbt'
    },
    'dry_run': {
        'env_vars': ['DBT_DRY_RUN'],
        'cli_flags': ['dry_run'],
        'required': False,
        'default': False,
        'type': 'bool',
        'help': 'Print commands without executing them'
    },
    'log_level': {
        'env_vars': ['DBT_LOG_LEVEL'],
        'cli_flags': ['log_level'],
        'required': False,
        'default': 'INFO',
        'choices': ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        'help': 'Logging level'
    },
    'docker_image': {
        'env_vars': ['DBT_DOCKER_IMAGE'],
        'cli_flags': ['docker_image'],
        'required': False,
        'default': 'ghcr.io/dbt-labs/dbt-core:latest',
        'help': 'Docker image to use'
    },
    'docker_platform': {
        'env_vars': ['DBT_DOCKER_PLATFORM'],
        'cli_flags': ['docker_platform'],
        'required': False,
        'default': None,
        'help': 'Platform for Docker (e.g., linux/amd64)'
    },
    'docker_volumes': {
        'env_vars': ['DBT_DOCKER_VOLUMES'],
        'cli_flags': ['docker_volumes'],
        'required': False,
        'default': [],
        'type': 'list',
        'help': 'Additional volume mounts (format: host:container)'
    },
    'docker_env': {
        'env_vars': ['DBT_DOCKER_ENV'],
        'cli_flags': ['docker_env'],
        'required': False,
        'default': [],
        'type': 'list',
        'help': 'Environment variables (format: KEY=VALUE)'
    },
    'docker_network': {
        'env_vars': ['DBT_DOCKER_NETWORK'],
        'cli_flags': ['docker_network'],
        'required': False,
        'default': 'host',
        'help': 'Docker network mode'
    },
    'docker_user': {
        'env_vars': ['DBT_DOCKER_USER'],
        'cli_flags': ['docker_user'],
        'required': False,
        'default': None,
        'help': 'User to run as inside container'
    },
    'docker_args': {
        'env_vars': ['DBT_DOCKER_ARGS'],
        'cli_flags': ['docker_args'],
        'required': False,
        'default': '',
        'help': 'Additional docker run arguments'
    },
    'shell_path': {
        'env_vars': ['DBT_SHELL_PATH', 'SHELL_PATH'],
        'cli_flags': ['shell_path', 'bash_path'],
        'required': False,
        'default': '/bin/bash',
        'help': 'Path to shell executable for bash runner'
    }
}

MODE_MAPPING: Dict[RunModes, Optional[str]] = {
    "all": None,
    "seeds": "seed",
    "models": "run",
    "tests": "test",
    "snapshots": "snapshot"
}

REVERSE_MODE_MAPPING: Dict[Optional[str], RunModes] = {v: k for k, v in MODE_MAPPING.items()}

NODE_TYPE_COMMAND_MAPPING: Dict[str, DependencyGraphNodeType] = {
    "models": "model",
    "macros": "macro",
    "seeds": "seed",
    "snapshots": "snapshot",
    "tests": "test"
}

MANIFEST_KEY_MAPPING = {
    "model": "nodes",
    "seed": "nodes",
    "snapshot": "nodes",
    "test": "nodes",
    "macro": "macros",
    "exposure": "exposures",
    "source": "sources"
}