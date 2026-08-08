"""Unit tests for Docker runner utilities."""
import pytest
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
from dbt_ci.runners.docker import (
    docker_runner,
    get_container_paths,
    get_docker_env,
    get_docker_volumes,
    parse_docker_args,
)
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


class TestDockerRunnerUser:
    """Test that docker_runner resolves the container user correctly."""

    def _make_mock_client(self):
        """Build a minimal docker client mock that records containers.run kwargs."""
        mock_container = MagicMock()
        mock_container.logs.return_value = iter([])
        mock_container.wait.return_value = {"StatusCode": 0}

        mock_client = MagicMock()
        mock_client.containers.run.return_value = mock_container
        return mock_client, mock_container

    def test_none_docker_user_falls_back_to_uid_gid(self, mock_runner_config):
        """docker_user=None should resolve to os.getuid():os.getgid(), not pass None."""
        config = mock_runner_config()  # docker_user is None by default
        mock_client, _ = self._make_mock_client()

        with patch("dbt_ci.runners.docker.docker.client.from_env", return_value=mock_client):
            docker_runner(["dbt", "debug"], config)

        _, kwargs = mock_client.containers.run.call_args
        expected_user = f"{os.getuid()}:{os.getgid()}"
        assert kwargs["user"] == expected_user, (
            f"Expected user='{expected_user}' but got user={kwargs['user']!r}. "
            "None docker_user must not be forwarded to the container."
        )

    def test_explicit_docker_user_is_respected(self, mock_runner_config):
        """An explicitly configured docker_user is forwarded as-is."""
        config = mock_runner_config({"docker_user": "1234:5678"})
        mock_client, _ = self._make_mock_client()

        with patch("dbt_ci.runners.docker.docker.client.from_env", return_value=mock_client):
            docker_runner(["dbt", "debug"], config)

        _, kwargs = mock_client.containers.run.call_args
        assert kwargs["user"] == "1234:5678"


class TestDockerRunnerOptions:
    """Test that the documented Docker options reach the container."""

    def _run(self, config, overrides=None):
        """Run docker_runner against a mocked client and return the containers.run kwargs."""
        mock_container = MagicMock()
        mock_container.logs.return_value = iter([])
        mock_container.wait.return_value = {"StatusCode": 0}
        mock_client = MagicMock()
        mock_client.containers.run.return_value = mock_container

        with patch("dbt_ci.runners.docker.docker.client.from_env", return_value=mock_client):
            result = docker_runner(["dbt", "debug"], config)

        _, kwargs = mock_client.containers.run.call_args
        return kwargs, mock_container, result

    def test_platform_is_forwarded(self, mock_runner_config):
        """--docker-platform is what makes dbt images work on Apple Silicon."""
        kwargs, _, _ = self._run(mock_runner_config({"docker_platform": "linux/amd64"}))
        assert kwargs["platform"] == "linux/amd64"

    def test_platform_omitted_when_unset(self, mock_runner_config):
        """Without an explicit platform, Docker picks the host's."""
        kwargs, _, _ = self._run(mock_runner_config({"docker_platform": None}))
        assert "platform" not in kwargs

    def test_network_is_forwarded(self, mock_runner_config):
        """--docker-network must reach the container, not silently default to bridge."""
        kwargs, _, _ = self._run(mock_runner_config({"docker_network": "host"}))
        assert kwargs["network_mode"] == "host"

    def test_container_is_removed(self, mock_runner_config):
        """Containers are cleaned up so repeated CI runs don't leak them."""
        _, container, _ = self._run(mock_runner_config())
        container.remove.assert_called_once_with(force=True)

    def test_container_is_removed_on_failure(self, mock_runner_config):
        """A failing dbt run must still clean up its container."""
        mock_container = MagicMock()
        mock_container.logs.return_value = iter([b"boom"])
        mock_container.wait.return_value = {"StatusCode": 1}
        mock_client = MagicMock()
        mock_client.containers.run.return_value = mock_container

        with patch("dbt_ci.runners.docker.docker.client.from_env", return_value=mock_client):
            with pytest.raises(SystemExit):
                docker_runner(["dbt", "debug"], mock_runner_config())

        mock_container.remove.assert_called_once_with(force=True)

    def test_dry_run_starts_no_container(self, mock_runner_config):
        """--dry-run must not execute dbt, consistent with the other runners."""
        mock_client = MagicMock()

        with patch("dbt_ci.runners.docker.docker.client.from_env", return_value=mock_client):
            result = docker_runner(["dbt", "debug"], mock_runner_config({"dry_run": True}))

        assert result is None
        mock_client.containers.run.assert_not_called()


class TestParseDockerArgs:
    """Test translation of --docker-args into Docker SDK keyword arguments."""

    def test_empty(self, mock_runner_config):
        """No extra args means no extra kwargs."""
        assert parse_docker_args(mock_runner_config({"docker_args": ""})) == {}

    def test_memory_and_cpus(self, mock_runner_config):
        """The documented '--memory=2g --cpus=2' example is translated."""
        result = parse_docker_args(mock_runner_config({"docker_args": "--memory=2g --cpus=2"}))

        assert result["mem_limit"] == "2g"
        assert result["nano_cpus"] == 2_000_000_000

    def test_space_separated_form(self, mock_runner_config):
        """'--flag value' works as well as '--flag=value'."""
        result = parse_docker_args(mock_runner_config({"docker_args": "--memory 512m"}))
        assert result["mem_limit"] == "512m"

    def test_env_vars_are_collected(self, mock_runner_config):
        """-e/--env entries are merged into the container environment."""
        result = parse_docker_args(mock_runner_config({"docker_args": "-e A=1 --env B=2"}))
        assert result["environment"] == {"A": "1", "B": "2"}

    def test_add_host(self, mock_runner_config):
        """--add-host maps onto extra_hosts."""
        result = parse_docker_args(
            mock_runner_config({"docker_args": "--add-host db:10.0.0.1"})
        )
        assert result["extra_hosts"] == {"db": "10.0.0.1"}

    def test_boolean_flag(self, mock_runner_config):
        """Valueless flags map to their constant."""
        result = parse_docker_args(mock_runner_config({"docker_args": "--privileged"}))
        assert result["privileged"] is True

    def test_unsupported_args_are_reported(self, mock_runner_config):
        """Args the SDK can't express are warned about rather than dropped silently."""
        config = mock_runner_config({"docker_args": "--cap-add SYS_ADMIN"})

        with patch("dbt_ci.runners.docker.logger") as mock_logger:
            result = parse_docker_args(config)

        assert result == {}
        mock_logger.warning.assert_called_once()

    def test_docker_args_env_merges_with_docker_env(self, mock_runner_config):
        """Env vars from --docker-args are added to those from --docker-env."""
        config = mock_runner_config({
            "docker_env": ["FROM_FLAG=1"],
            "docker_args": "-e FROM_ARGS=2",
        })
        mock_container = MagicMock()
        mock_container.logs.return_value = iter([])
        mock_container.wait.return_value = {"StatusCode": 0}
        mock_client = MagicMock()
        mock_client.containers.run.return_value = mock_container

        with patch("dbt_ci.runners.docker.docker.client.from_env", return_value=mock_client):
            docker_runner(["dbt", "debug"], config)

        _, kwargs = mock_client.containers.run.call_args
        assert kwargs["environment"] == {"FROM_FLAG": "1", "FROM_ARGS": "2"}
