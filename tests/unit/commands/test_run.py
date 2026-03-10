"""Unit tests for the run command."""
import pytest
from unittest.mock import MagicMock, patch, call
from argparse import Namespace
from dbt_ci.commands.run.index import run as index, run_with_mode


class TestRunCommand:
    """Test the run command."""
    
    @patch('dbt_ci.commands.run.index.CacheManager')
    @patch('dbt_ci.commands.run.index.DbtGraph')
    @patch('dbt_ci.commands.run.index.logger.error')
    @patch('dbt_ci.commands.run.index.click.secho')
    def test_run_no_cache(
        self,
        mock_secho,
        mock_logger_error,
        mock_graph,
        mock_cache
    ):
        """Test run command exits when no cache is found."""
        # Setup mocks
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = None
        mock_cache.return_value = mock_cache_instance
        # Run command
        args = Namespace(
            dbt_project_dir='/dbt',
            dry_run=False
        )
        index(args)
        
        # Verify message was logged
        mock_logger_error.assert_called_with(
            "No cache found, please run 'dbt-ci init' first to generate the necessary manifest files and cache for comparison."
        )
    
    @patch('dbt_ci.commands.run.index.CacheManager')
    @patch('dbt_ci.commands.run.index.DbtGraph')
    @patch('dbt_ci.commands.run.index.get_node_ids_from_structured_nodes')
    @patch('dbt_ci.commands.run.index.run_with_mode')
    @patch('dbt_ci.commands.run.index.logger.info')
    @patch('dbt_ci.commands.run.index.click.secho')
    def test_run_no_modified_nodes(
        self,
        mock_secho,
        mock_logger_info,
        mock_run_mode,
        mock_get_nodes,
        mock_graph,
        mock_cache
    ):
        """Test run command exits when no modified nodes are found."""
        # Setup mocks
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = {
            "modified_nodes": None,
            "new_nodes": None,
            "deleted_nodes": None
        }
        mock_cache.return_value = mock_cache_instance
        mock_get_nodes.return_value = []
        
        # Run command - expect it to exit with code 0
        args = Namespace(
            dbt_project_dir='/dbt',
            dry_run=False
        )
        with pytest.raises(SystemExit) as exc_info:
            index(args)
        
        # Verify it exited with code 0
        assert exc_info.value.code == 0
        
        # Verify appropriate message was logged
        mock_logger_info.assert_any_call("No modified, new, or deleted nodes found in cache, skipping...")
    
    @patch('dbt_ci.commands.run.index.CacheManager')
    @patch('dbt_ci.commands.run.index.DbtGraph')
    @patch('dbt_ci.commands.run.index.get_node_ids_from_structured_nodes')
    @patch('dbt_ci.commands.run.index.run_with_mode')
    @patch('dbt_ci.commands.run.index.click.secho')
    @patch('dbt_ci.commands.run.index.click.echo')
    def test_run_with_modified_nodes(
        self,
        mock_echo,
        mock_secho,
        mock_run_mode,
        mock_get_nodes,
        mock_graph,
        mock_cache
    ):
        """Test run command with modified nodes."""
        # Setup mocks
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = {
            "modified_nodes": {"model": {"model.project.model1": {}}},
            "new_nodes": {"model": {"model.project.model2": {}}},
            "deleted_nodes": None
        }
        mock_cache.return_value = mock_cache_instance
        mock_get_nodes.side_effect = [
            ['model.project.model1'],  # modified
            ['model.project.model2'],  # new
            []  # deleted
        ]
        
        mock_graph_instance = MagicMock()
        mock_graph_instance.to_dict.return_value = {}
        mock_graph.return_value = mock_graph_instance
        
        # Run command
        args = Namespace(
            dbt_project_dir='/dbt',
            nodes='models',
            dry_run=False
        )
        index(args)
        
        # Verify run_with_mode was called
        mock_run_mode.assert_called_once()
        call_args = mock_run_mode.call_args
        assert call_args[1]['mode'] == 'models'
    
    @patch('dbt_ci.commands.run.index.click.echo')
    @patch('dbt_ci.commands.run.index.sys.exit')
    def test_run_error_handling(
        self,
        mock_exit,
        mock_echo
    ):
        """Test run command error handling."""
        # Run with invalid kwargs to trigger exception
        args = Namespace(
            dbt_project_dir='/dbt',
            dry_run=False
        )
        index(args)
        
        # Verify error was handled
        mock_exit.assert_called_once_with(1)


class TestRunWithMode:
    """Test the run_with_mode helper function."""
    
    @patch('dbt_ci.commands.run.index.run_dbt_command')
    @patch('dbt_ci.commands.run.index.get_downstream_dependencies')
    @patch('dbt_ci.commands.run.index.filter_node_ids_by_type')
    @patch('dbt_ci.commands.run.index.click.echo')
    def test_run_with_mode_all(
        self,
        mock_echo,
        mock_filter,
        mock_downstream,
        mock_run_cmd
    ):
        """Test run_with_mode with 'all' mode."""
        # Setup
        variables = Namespace(dry_run=False)
        target_graph = MagicMock()
        target_graph.to_dict.return_value = {
            "model": {},
            "seed": {},
            "snapshot": {},
            "test": {}
        }
        
        modified_nodes_dict = {
            "modified_nodes": ["model.project.model1"],
            "new_nodes": ["model.project.model2"],
            "deleted_nodes": []
        }
        modified_nodes = ["model.project.model1", "model.project.model2"]
        
        mock_downstream.return_value = []
        mock_filter.return_value = ["model.project.model1", "model.project.model2"]
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run_cmd.return_value = mock_result
        
        # Run
        run_with_mode('all', variables, target_graph, modified_nodes_dict, modified_nodes)
        
        # Verify all command types were attempted
        # Should run: seed, run, test, snapshot
        assert mock_run_cmd.call_count >= 1
    
    @patch('dbt_ci.commands.run.index.run_dbt_command')
    @patch('dbt_ci.commands.run.index.get_downstream_dependencies')
    @patch('dbt_ci.commands.run.index.filter_node_ids_by_type')
    @patch('dbt_ci.commands.run.index.click.echo')
    def test_run_with_mode_models_only(
        self,
        mock_echo,
        mock_filter,
        mock_downstream,
        mock_run_cmd
    ):
        """Test run_with_mode with 'models' mode."""
        # Setup
        variables = Namespace(dry_run=False)
        target_graph = MagicMock()
        target_graph.to_dict.return_value = {"model": {}}
        
        modified_nodes_dict = {
            "modified_nodes": ["model.project.model1"],
            "new_nodes": [],
            "deleted_nodes": []
        }
        modified_nodes = ["model.project.model1"]
        
        mock_downstream.return_value = ["model.project.model3"]
        mock_filter.return_value = ["model.project.model1", "model.project.model3"]
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run_cmd.return_value = mock_result
        
        # Run
        run_with_mode('models', variables, target_graph, modified_nodes_dict, modified_nodes)
        
        # Verify run command was called
        mock_run_cmd.assert_called_once()
    
    @patch('dbt_ci.commands.run.index.get_downstream_dependencies')
    @patch('dbt_ci.commands.run.index.filter_node_ids_by_type')
    @patch('dbt_ci.commands.run.index.logger.info')
    def test_run_with_mode_no_nodes(
        self,
        mock_logger_info,
        mock_filter,
        mock_downstream
    ):
        """Test run_with_mode when no nodes match the filter."""
        # Setup
        variables = Namespace(dry_run=False)
        target_graph = MagicMock()
        target_graph.to_dict.return_value = {}
        
        modified_nodes_dict = {
            "modified_nodes": [],
            "new_nodes": [],
            "deleted_nodes": []
        }
        modified_nodes = []
        
        mock_downstream.return_value = []
        mock_filter.return_value = []
        
        # Run
        run_with_mode('models', variables, target_graph, modified_nodes_dict, modified_nodes)
        
        # Verify no models message was logged
        mock_logger_info.assert_any_call("No models to run")
    
    @patch('dbt_ci.commands.run.index.run_dbt_command')
    @patch('dbt_ci.commands.run.index.get_downstream_dependencies')
    @patch('dbt_ci.commands.run.index.filter_node_ids_by_type')
    @patch('dbt_ci.commands.run.index.logger.info')
    def test_run_with_mode_dry_run(
        self,
        mock_logger_info,
        mock_filter,
        mock_downstream,
        mock_run_cmd
    ):
        """Test run_with_mode in dry run mode."""
        # Setup
        variables = Namespace(dry_run=True)
        target_graph = MagicMock()
        target_graph.to_dict.return_value = {"model": {}}
        
        modified_nodes_dict = {
            "modified_nodes": ["model.project.model1"],
            "new_nodes": [],
            "deleted_nodes": []
        }
        modified_nodes = ["model.project.model1"]
        
        mock_downstream.return_value = []
        mock_filter.return_value = ["model.project.model1"]
        
        # Run
        run_with_mode('models', variables, target_graph, modified_nodes_dict, modified_nodes)
        
        # Verify dbt command was NOT executed
        mock_run_cmd.assert_not_called()
        
        # Verify dry run message was logged
        mock_logger_info.assert_any_call("DRY RUN: Command would be executed")
