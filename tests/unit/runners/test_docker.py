"""Unit tests for Docker runner utilities."""
import pytest
import os
from pathlib import Path
from dbt_ci.runners.docker import get_docker_env, get_docker_volumes, get_container_paths
from dbt_ci.utilities.paths import get_absolute_path


class TestGetDockerEnv:
    """Test get_docker_env function."""
    
    def test_get_docker_env_empty(self, mock_runner_config):
        """Test that empty docker_env returns empty dict."""
        config = mock_runner_config()
        result = get_docker_env(config)
        # Should return empty dict when docker_env is empty
        assert result == {}
    
    def test_get_docker_env_none(self, mock_runner_config):
        """Test that None docker_env returns empty dict."""
        config = mock_runner_config({'docker_env': None})
        result = get_docker_env(config)
        # Should return empty dict when docker_env is None
        assert result == {}
    
    def test_get_docker_env_single(self, mock_runner_config):
        """Test parsing single environment variable."""
        config = mock_runner_config({'docker_env': ['MY_VAR=test_value']})
        result = get_docker_env(config)
        
        # Should include only custom env var
        assert result['MY_VAR'] == 'test_value'
        assert len(result) == 1
    
    def test_get_docker_env_multiple(self, mock_runner_config):
        """Test parsing multiple environment variables."""
        config = mock_runner_config({'docker_env': [
            'VAR1=value1',
            'VAR2=value2',
            'VAR3=value3'
        ]})
        result = get_docker_env(config)
        
        # Should include only custom env vars
        assert result['VAR1'] == 'value1'
        assert result['VAR2'] == 'value2'
        assert result['VAR3'] == 'value3'
        assert len(result) == 3
    
    def test_get_docker_env_with_equals_in_value(self, mock_runner_config):
        """Test parsing env var with equals sign in value."""
        config = mock_runner_config({'docker_env': ['DATABASE_URL=postgres://user:pass@host/db?param=value']})
        result = get_docker_env(config)
        
        assert result['DATABASE_URL'] == 'postgres://user:pass@host/db?param=value'
    
    # Config vars should be passed via docker_env explicitly, not automatically
    def test_get_docker_env_includes_config_vars(self, mock_runner_config):
        """Test that config vars can be passed via docker_env."""
        config = mock_runner_config({
            'docker_env': [
                'DBT_PROJECT_DIR=/dbt',
                'DBT_PROFILES_DIR=/dbt',
                'DBT_STATE=/dbt/.dbtstate'
            ]
        })
        result = get_docker_env(config)
        
        assert result['DBT_PROJECT_DIR'] == '/dbt'
        assert result['DBT_PROFILES_DIR'] == '/dbt'
        assert result['DBT_STATE'] == '/dbt/.dbtstate'

    def test_get_docker_volumes_with_config_vars(self, mock_runner_config):
        """Test that config vars are included in Docker volumes."""
        config = mock_runner_config({
            'docker_volumes': ['./data:/data:ro'],
        })
        result = get_docker_volumes(config)
        
        assert any(path.endswith('data')
            and Path(path).is_absolute()
            for path in result.keys()
        )



class TestGetDockerVolumes:
    """Test get_docker_volumes function."""
    
    def test_get_docker_volumes_empty(self, mock_runner_config):
        """Test that empty docker_volumes returns None."""
        config = mock_runner_config()
        result = get_docker_volumes(config)
        assert result is None
    
    def test_get_docker_volumes_none(self, mock_runner_config):
        """Test that None docker_volumes returns None."""
        config = mock_runner_config({'docker_volumes': None})
        result = get_docker_volumes(config)
        assert result is None
    
    def test_get_docker_volumes_single_rw(self, mock_runner_config):
        """Test parsing single volume with default read-write mode."""
        config = mock_runner_config({'docker_volumes': ['/host/path:/container/path']})
        result = get_docker_volumes(config)
        
        assert '/host/path' in result
        assert result['/host/path']['bind'] == '/container/path'
        assert result['/host/path']['mode'] == 'rw'
    
    def test_get_docker_volumes_with_mode(self, mock_runner_config):
        """Test parsing volume with explicit mode."""
        config = mock_runner_config({'docker_volumes': ['/host/path:/container/path:ro']})
        result = get_docker_volumes(config)
        
        assert '/host/path' in result
        assert result['/host/path']['bind'] == '/container/path'
        assert result['/host/path']['mode'] == 'ro'
    
    def test_get_docker_volumes_multiple(self, mock_runner_config):
        """Test parsing multiple volumes."""
        config = mock_runner_config({'docker_volumes': [
            '/path1:/container1',
            '/path2:/container2:ro',
            '/path3:/container3:rw'
        ]})
        result = get_docker_volumes(config)
        
        assert len(result) == 3
        assert result['/path1']['bind'] == '/container1'
        assert result['/path2']['bind'] == '/container2'
        assert result['/path2']['mode'] == 'ro'
        assert result['/path3']['bind'] == '/container3'
        assert result['/path3']['mode'] == 'rw'
    
    def test_get_docker_volumes_relative_path(self, mock_runner_config, tmp_path):
        """Test that relative paths are converted to absolute."""
        # Create a relative path that will be resolved
        original_cwd = os.getcwd()
        
        try:
            os.chdir(tmp_path)
            config = mock_runner_config({'docker_volumes': ['./relative:/container']})
            result = get_docker_volumes(config)
            
            # Should contain absolute path
            assert any(path.endswith('relative') and Path(path).is_absolute()
                      for path in result.keys())
        finally:
            os.chdir(original_cwd)


class TestGetContainerPaths:
    """Test get_container_paths resolves dbt_project_dir to container paths."""

    def test_relative_project_dir_with_relative_volume_key(self, mock_runner_config):
        """Relative project-dir matches a relative volume key (both normalize to the same absolute path)."""
        config = mock_runner_config({
            'dbt_project_dir': 'dbt',
            'docker_volumes': ['dbt:/container/dbt:rw'],
            'docker_env': [],
        })
        result = get_container_paths(config)
        assert result.get('dbt_project_dir') == '/container/dbt'

    def test_relative_project_dir_with_absolute_volume_key(self, mock_runner_config):
        """Relative project-dir matches an absolute volume key (the core bug case).

        Simulates a user writing '${PWD}/dbt:/container/dbt:rw', which the config
        loader expands to an absolute path before passing it in.
        """
        abs_dbt = get_absolute_path('dbt')
        config = mock_runner_config({
            'dbt_project_dir': 'dbt',
            'docker_volumes': [f'{abs_dbt}:/container/dbt:rw'],
            'docker_env': [],
        })
        result = get_container_paths(config)
        assert result.get('dbt_project_dir') == '/container/dbt'

    def test_project_dir_is_subdirectory_of_mounted_volume(self, mock_runner_config):
        """project-dir nested under a mounted volume resolves with the relative suffix."""
        config = mock_runner_config({
            'dbt_project_dir': 'workspace/dbt',
            'docker_volumes': ['workspace:/container/workspace:rw'],
            'docker_env': [],
        })
        result = get_container_paths(config)
        assert result.get('dbt_project_dir') == '/container/workspace/dbt'

    def test_docker_env_takes_priority_over_volume_map(self, mock_runner_config):
        """DBT_PROJECT_DIR in docker_env overrides the volume map lookup."""
        abs_dbt = get_absolute_path('dbt')
        config = mock_runner_config({
            'dbt_project_dir': 'dbt',
            'docker_volumes': [f'{abs_dbt}:/volume/dbt:rw'],
            'docker_env': ['DBT_PROJECT_DIR=/env/dbt'],
        })
        result = get_container_paths(config)
        assert result.get('dbt_project_dir') == '/env/dbt'

    def test_no_volume_match_omits_project_dir(self, mock_runner_config):
        """When no volume covers project-dir the key is absent (no crash)."""
        config = mock_runner_config({
            'dbt_project_dir': 'dbt',
            'docker_volumes': ['/some/other/path:/container/other:rw'],
            'docker_env': [],
        })
        result = get_container_paths(config)
        assert 'dbt_project_dir' not in result
