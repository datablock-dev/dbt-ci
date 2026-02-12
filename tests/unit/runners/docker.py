"""Unit tests for Docker runner utilities."""
import pytest
import os
from pathlib import Path
from src.runners.docker import get_docker_env, get_docker_volumes


class TestGetDockerEnv:
    """Test get_docker_env function."""
    
    def test_get_docker_env_empty(self, mock_runner_config):
        """Test that empty docker_env returns None."""
        result = get_docker_env(mock_runner_config)
        assert result is None
    
    def test_get_docker_env_none(self, mock_runner_config):
        """Test that None docker_env returns None."""
        mock_runner_config['docker_env'] = None
        result = get_docker_env(mock_runner_config)
        assert result is None
    
    def test_get_docker_env_single(self, mock_runner_config):
        """Test parsing single environment variable."""
        mock_runner_config['docker_env'] = ['MY_VAR=test_value']
        result = get_docker_env(mock_runner_config)
        
        assert result == {'MY_VAR': 'test_value'}
    
    def test_get_docker_env_multiple(self, mock_runner_config):
        """Test parsing multiple environment variables."""
        mock_runner_config['docker_env'] = [
            'VAR1=value1',
            'VAR2=value2',
            'VAR3=value3'
        ]
        result = get_docker_env(mock_runner_config)
        
        assert result == {
            'VAR1': 'value1',
            'VAR2': 'value2',
            'VAR3': 'value3'
        }
    
    def test_get_docker_env_with_equals_in_value(self, mock_runner_config):
        """Test parsing env var with equals sign in value."""
        mock_runner_config['docker_env'] = ['DATABASE_URL=postgres://user:pass@host/db?param=value']
        result = get_docker_env(mock_runner_config)
        
        assert result == {'DATABASE_URL': 'postgres://user:pass@host/db?param=value'}


class TestGetDockerVolumes:
    """Test get_docker_volumes function."""
    
    def test_get_docker_volumes_empty(self, mock_runner_config):
        """Test that empty docker_volumes returns None."""
        result = get_docker_volumes(mock_runner_config)
        assert result is None
    
    def test_get_docker_volumes_none(self, mock_runner_config):
        """Test that None docker_volumes returns None."""
        mock_runner_config['docker_volumes'] = None
        result = get_docker_volumes(mock_runner_config)
        assert result is None
    
    def test_get_docker_volumes_single_rw(self, mock_runner_config):
        """Test parsing single volume with default read-write mode."""
        mock_runner_config['docker_volumes'] = ['/host/path:/container/path']
        result = get_docker_volumes(mock_runner_config)
        
        assert '/host/path' in result
        assert result['/host/path']['bind'] == '/container/path'
        assert result['/host/path']['mode'] == 'rw'
    
    def test_get_docker_volumes_with_mode(self, mock_runner_config):
        """Test parsing volume with explicit mode."""
        mock_runner_config['docker_volumes'] = ['/host/path:/container/path:ro']
        result = get_docker_volumes(mock_runner_config)
        
        assert '/host/path' in result
        assert result['/host/path']['bind'] == '/container/path'
        assert result['/host/path']['mode'] == 'ro'
    
    def test_get_docker_volumes_multiple(self, mock_runner_config):
        """Test parsing multiple volumes."""
        mock_runner_config['docker_volumes'] = [
            '/path1:/container1',
            '/path2:/container2:ro',
            '/path3:/container3:rw'
        ]
        result = get_docker_volumes(mock_runner_config)
        
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
            mock_runner_config['docker_volumes'] = ['./relative:/container']
            result = get_docker_volumes(mock_runner_config)
            
            # Should contain absolute path
            assert any(path.endswith('relative') and Path(path).is_absolute() 
                      for path in result.keys())
        finally:
            os.chdir(original_cwd)
