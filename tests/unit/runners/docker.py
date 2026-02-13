"""Unit tests for Docker runner utilities."""
import pytest
import os
from pathlib import Path
from src.runners.docker import get_docker_env, get_docker_volumes
from src.utilities.paths import get_absolute_path


class TestGetDockerEnv:
    """Test get_docker_env function."""
    
    def test_get_docker_env_empty(self, mock_runner_config):
        """Test that empty docker_env still returns config vars."""
        config = mock_runner_config()
        result = get_docker_env(config)
        # Should still include config vars even when docker_env is empty
        assert 'DBT_PROJECT_DIR' in result
        assert 'DBT_PROFILES_DIR' in result
        assert 'DBT_STATE' in result
    
    def test_get_docker_env_none(self, mock_runner_config):
        """Test that None docker_env still returns config vars."""
        config = mock_runner_config({'docker_env': None})
        result = get_docker_env(config)
        # Should still include config vars even when docker_env is None
        assert 'DBT_PROJECT_DIR' in result
        assert 'DBT_PROFILES_DIR' in result
    
    def test_get_docker_env_single(self, mock_runner_config):
        """Test parsing single environment variable."""
        config = mock_runner_config({'docker_env': ['MY_VAR=test_value']})
        result = get_docker_env(config)
        
        # Should include both custom env var and config vars
        assert result['MY_VAR'] == 'test_value'
        assert 'DBT_PROJECT_DIR' in result
    
    def test_get_docker_env_multiple(self, mock_runner_config):
        """Test parsing multiple environment variables."""
        config = mock_runner_config({'docker_env': [
            'VAR1=value1',
            'VAR2=value2',
            'VAR3=value3'
        ]})
        result = get_docker_env(config)
        
        # Should include all custom env vars and config vars
        assert result['VAR1'] == 'value1'
        assert result['VAR2'] == 'value2'
        assert result['VAR3'] == 'value3'
        assert 'DBT_PROJECT_DIR' in result
    
    def test_get_docker_env_with_equals_in_value(self, mock_runner_config):
        """Test parsing env var with equals sign in value."""
        config = mock_runner_config({
            'docker_env': [
                'DATABASE_URL=postgres://user:pass@host/db?param=value',
                "DBT_PROFILES_DIR=/usr/app",
                "DBT_PROJECT_DIR=/usr/app",
                "DBT_STATE=/usr/app/.dbtstate"
            ]
        })
        result = get_docker_env(config)
        
        assert result['DATABASE_URL'] == 'postgres://user:pass@host/db?param=value'
        assert result['DBT_PROFILES_DIR'] == '/usr/app'
        assert result['DBT_PROJECT_DIR'] == '/usr/app'
        assert result['DBT_STATE'] == '/usr/app/.dbtstate'
    
    # Should return the correct absolute paths for config variables
    def test_get_docker_env_includes_config_vars(self, mock_runner_config):
        """Test that config vars are included in Docker env."""
        config = mock_runner_config({
            'dbt_project_dir': '/dbt',
            'profiles_dir': '/dbt',
            "reference_state": "/dbt/.dbtstate"
        })
        result = get_docker_env(config)
        
        assert result['DBT_PROJECT_DIR'] == '/dbt'
        assert result['DBT_PROFILES_DIR'] == '/dbt'
        assert result['DBT_STATE'] == '/dbt/.dbtstate'

    def test_get_docker_volumes_with_config_vars(self, mock_runner_config):
        """Test that config vars are included in Docker volumes."""
        config = mock_runner_config({
            'docker_volumes': [
                './dbt:/usr/app:rw',
                "./dbt/.dbtstate:/dbtstate:ro"
            ],
        })
        result = get_docker_volumes(config)
        assert any(path.endswith('dbt')
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
