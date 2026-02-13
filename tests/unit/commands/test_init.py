"""Unit tests for the init command."""
import pytest
from unittest.mock import MagicMock, patch, call
from argparse import Namespace
from src.commands.init import init


class TestInitCommand:
    """Test the init command."""
    
    @patch('src.commands.init.CacheManager')
    @patch('src.commands.init.Variables')
    @patch('src.commands.init.init_storage_connector')
    @patch('src.commands.init.resolve_dbt_commands')
    @patch('src.commands.init.run_dbt_command')
    @patch('src.commands.init.DbtGraph')
    @patch('src.commands.init.get_manifest_file')
    @patch('src.commands.init.click.secho')
    def test_init_success_no_modified_nodes(
        self,
        mock_secho,
        mock_get_manifest,
        mock_graph,
        mock_run_cmd,
        mock_resolve_cmds,
        mock_storage,
        mock_vars,
        mock_cache
    ):
        """Test successful init with no modified nodes."""
        # Setup mocks
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance
        
        mock_vars_instance = MagicMock()
        mock_vars_instance.to_namespace.return_value = Namespace(
            dbt_project_dir='/dbt',
            reference_state='/dbt/.dbtstate',
            runner='local',
            reference_target=None,
            target_config={'type': 'bigquery'}
        )
        mock_vars.return_value = mock_vars_instance
        
        mock_storage.return_value = None
        
        # Mock resolve_dbt_commands to return a list of command args
        mock_resolve_cmds.return_value = ['compile', '--project-dir', '/dbt']
        
        # Mock run_dbt_command to return None (no modified nodes)
        mock_run_cmd.return_value = None
        
        # Mock DbtGraph
        mock_graph_instance = MagicMock()
        mock_graph_instance.to_dict.return_value = {}
        mock_graph.return_value = mock_graph_instance
        
        # Mock manifest file
        mock_get_manifest.return_value = {'metadata': {}}
        
        # Run init - expect SystemExit(0)
        with pytest.raises(SystemExit) as exc_info:
            init(dbt_project_dir='/dbt', reference_state='/dbt/.dbtstate')
        
        # Verify cache was written with no modified nodes
        mock_cache_instance.write_cache.assert_called()
        
        # Verify exit code
        assert exc_info.value.code == 0
    
    @patch('src.commands.init.CacheManager')
    @patch('src.commands.init.Variables')
    @patch('src.commands.init.init_storage_connector')
    @patch('src.commands.init.resolve_dbt_commands')
    @patch('src.commands.init.run_dbt_command')
    @patch('src.commands.init.DbtGraph')
    @patch('src.commands.init.get_manifest_file')
    @patch('src.commands.init.get_structured_modified_nodes')
    @patch('src.commands.init.get_nodes')
    @patch('src.commands.init.get_deleted_nodes')
    @patch('src.commands.init.get_new_nodes')
    @patch('src.commands.init.click.secho')
    def test_init_success_with_modified_nodes(
        self,
        mock_secho,
        mock_get_new,
        mock_get_deleted,
        mock_get_nodes,
        mock_structured,
        mock_get_manifest,
        mock_graph,
        mock_run_cmd,
        mock_resolve_cmds,
        mock_storage,
        mock_vars,
        mock_cache
    ):
        """Test successful init with modified nodes."""
        # Setup mocks
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance
        
        mock_vars_instance = MagicMock()
        mock_vars_instance.to_namespace.return_value = Namespace(
            dbt_project_dir='/dbt',
            reference_state='/dbt/.dbtstate',
            runner='local',
            reference_target='prod',
            target_config={'type': 'bigquery'}
        )
        mock_vars.return_value = mock_vars_instance
        
        mock_storage.return_value = None
        
        # Mock resolve_dbt_commands to return command args
        mock_resolve_cmds.return_value = ['compile', '--project-dir', '/dbt']
        
        # Mock run_dbt_command to return modified node IDs (as CompletedProcess-like object)
        mock_result = MagicMock()
        mock_result.stdout = "model.project.model1\nmodel.project.model2"
        mock_run_cmd.return_value = mock_result
        
        # Mock graph structure
        mock_graph_instance = MagicMock()
        mock_graph_instance.to_dict.return_value = {
            "model": {
                "model.project.model1": {"name": "model1", "resource_type": "model"}
            }
        }
        mock_graph.return_value = mock_graph_instance
        
        mock_get_nodes.return_value = {
            "model.project.model1": {"name": "model1", "resource_type": "model"}
        }
        
        mock_structured.return_value = {
            "model": {
                "model.project.model1": {"name": "model1", "resource_type": "model"}
            }
        }
        
        mock_get_deleted.return_value = []
        mock_get_new.return_value = []
        
        mock_get_manifest.return_value = {"metadata": {}}
        
        # Run init - should complete successfully without raising SystemExit
        init(dbt_project_dir='/dbt', reference_state='/dbt/.dbtstate', reference_target='prod')
        
        # Verify cache was written
        assert mock_cache_instance.write_cache.call_count >= 2
        
        # Verify resolve_dbt_commands was called
        assert mock_resolve_cmds.call_count >= 1
    
    @patch('src.commands.init.CacheManager')
    @patch('src.commands.init.Variables')
    @patch('src.commands.init.click.secho')
    def test_init_error_handling(
        self,
        mock_secho,
        mock_vars,
        mock_cache
    ):
        """Test init error handling."""
        # Setup mocks to raise an exception
        mock_vars.side_effect = Exception("Configuration error")
        
        # Run init - expect SystemExit(1)
        with pytest.raises(SystemExit) as exc_info:
            init(dbt_project_dir='/dbt')
        
        # Verify exit was called with error code
        assert exc_info.value.code == 1
    
    @patch('src.commands.init.CacheManager')
    @patch('src.commands.init.Variables')
    @patch('src.commands.init.init_storage_connector')
    @patch('src.commands.init.resolve_dbt_commands')
    @patch('src.commands.init.run_dbt_command')
    @patch('src.commands.init.DbtGraph')
    @patch('src.commands.init.get_manifest_file')
    @patch('src.commands.init.click.secho')
    def test_init_with_reference_target(
        self,
        mock_secho,
        mock_get_manifest,
        mock_graph,
        mock_run_cmd,
        mock_resolve_cmds,
        mock_storage,
        mock_vars,
        mock_cache
    ):
        """Test init with reference target specified."""
        # Setup mocks
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance
        
        mock_vars_instance = MagicMock()
        mock_vars_instance.to_namespace.return_value = Namespace(
            dbt_project_dir='/dbt',
            reference_state='/dbt/.dbtstate',
            runner='local',
            reference_target='prod',
            target_config={'type': 'bigquery'}
        )
        mock_vars.return_value = mock_vars_instance
        
        mock_storage.return_value = None
        
        # Mock resolve_dbt_commands to return command args
        mock_resolve_cmds.return_value = ['compile', '--project-dir', '/dbt', '--target', 'prod']
        
        # Mock run_dbt_command to return None (no modified nodes)
        mock_run_cmd.return_value = None
        
        # Mock DbtGraph
        mock_graph_instance = MagicMock()
        mock_graph_instance.to_dict.return_value = {}
        mock_graph.return_value = mock_graph_instance
        
        # Mock manifest file
        mock_get_manifest.return_value = {'metadata': {}}
        
        # Run init - expect SystemExit(0)
        with pytest.raises(SystemExit) as exc_info:
            init(dbt_project_dir='/dbt', reference_state='/dbt/.dbtstate', reference_target='prod')
        
        # Verify resolve_dbt_commands was called - it should use reference target internally
        mock_resolve_cmds.assert_called()
        
        # Verify exit code
        assert exc_info.value.code == 0


class TestResolveManifestFromStorage:
    """Test the resolve_manifest_file_from_storage helper function."""
    
    @patch('src.commands.init.Path')
    @patch('src.commands.init.logger')
    def test_resolve_manifest_creates_directory(self, mock_logger, mock_path):
        """Test that the function creates the necessary directory."""
        from src.commands.init import resolve_manifest_file_from_storage
        
        # Setup mocks
        storage_connector = {
            "download": MagicMock(return_value={"metadata": {}})
        }
        state_uri = "s3://bucket/path"
        variables = Namespace(
            reference_state=None,
            dbt_project_dir='dbt',
            state='dbt/.dbtstate'
        )
        
        # Mock Path operations
        mock_path_instance = MagicMock()
        mock_path.return_value = mock_path_instance
        mock_path.cwd.return_value = mock_path_instance
        
        # Run function
        resolve_manifest_file_from_storage((storage_connector, state_uri), variables)
        
        # Verify download was called
        storage_connector["download"].assert_called_once_with(state_uri)
