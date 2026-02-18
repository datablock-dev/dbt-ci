"""Unit tests for the delete command."""
import pytest
from unittest.mock import MagicMock, patch
from argparse import Namespace
from src.commands.delete import delete


class TestDeleteCommand:
    """Test the delete command."""
    
    @patch('src.commands.delete.DbtGraph')
    @patch('src.commands.delete.CacheManager')
    @patch('src.commands.delete.click.secho')
    @patch('src.commands.delete.click.echo')
    def test_delete_no_cache(
        self,
        mock_echo,
        mock_secho,
        mock_cache,
        mock_graph
    ):
        """Test delete command exits when no cache is found."""
        # Setup mocks
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = None
        mock_cache.return_value = mock_cache_instance
        
        mock_graph_instance = MagicMock()
        mock_graph.return_value = mock_graph_instance
        
        # Run command (now expects Namespace args directly)
        args = Namespace(
            dbt_project_dir='/dbt',
            reference_state='/dbt/.dbtstate',
            dry_run=False,
            runner='local',
            target_config={'type': 'bigquery'}
        )
        delete(args)
        
        # Verify message was shown
        mock_echo.assert_called_with(
            "No cache found, please run 'dbt-ci init' first to generate the necessary manifest files and cache for comparison."
        )
    
    @patch('src.commands.delete.CacheManager')
    @patch('src.commands.delete.DbtGraph')
    @patch('src.commands.delete.get_connector')
    @patch('src.commands.delete.get_node_ids_from_structured_nodes')
    @patch('src.commands.delete.click.secho')
    @patch('src.commands.delete.click.echo')
    def test_delete_no_deleted_nodes(
        self,
        mock_echo,
        mock_secho,
        mock_get_nodes,
        mock_get_connector,
        mock_graph,
        mock_vars,
        mock_cache
    ):
        """Test delete command when no deleted nodes are found."""
        # Setup mocks
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = {
            "deleted_nodes": None
        }
        mock_cache.return_value = mock_cache_instance
        
        mock_vars_instance = MagicMock()
        mock_vars_instance.to_namespace.return_value = Namespace(
            dbt_project_dir='/dbt',
            dry_run=False,
            target_config={'type': 'bigquery'}
        )
        mock_vars.return_value = mock_vars_instance
        
        mock_get_nodes.return_value = []
        
        # Run command
        delete(dbt_project_dir='/dbt')
        
        # Verify appropriate message was shown
        mock_echo.assert_any_call("No deleted nodes found in cache, skipping...")
    
    @patch('src.commands.delete.CacheManager')
    @patch('src.commands.delete.DbtGraph')
    @patch('src.commands.delete.get_connector')
    @patch('src.commands.delete.get_node_ids_from_structured_nodes')
    @patch('src.commands.delete.get_nodes')
    @patch('src.commands.delete.click.secho')
    @patch('src.commands.delete.click.echo')
    @patch('src.commands.delete.sys.exit')
    def test_delete_with_deleted_nodes(
        self,
        mock_exit,
        mock_echo,
        mock_secho,
        mock_get_nodes_util,
        mock_get_node_ids,
        mock_get_connector,
        mock_graph,
        mock_vars,
        mock_cache
    ):
        """Test delete command with deleted nodes."""
        # Setup mocks
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = {
            "deleted_nodes": {"model": {"model.project.old_model": {}}}
        }
        mock_cache.return_value = mock_cache_instance
        
        mock_vars_instance = MagicMock()
        namespace = Namespace(
            dbt_project_dir='/dbt',
            dry_run=False,
            target_config={'type': 'bigquery'}
        )
        mock_vars_instance.to_namespace.return_value = namespace
        mock_vars.return_value = mock_vars_instance
        
        mock_get_node_ids.return_value = ['model.project.old_model']
        
        mock_get_nodes_util.return_value = {
            'model.project.old_model': {
                'resource_type': 'model',
                'name': 'old_model',
                'database': 'my_db',
                'schema': 'my_schema',
                'config': {'alias': None}
            }
        }
        
        mock_graph_instance = MagicMock()
        mock_graph_instance.to_dict.return_value = {}
        mock_graph.return_value = mock_graph_instance
        
        mock_delete_func = MagicMock()
        mock_get_connector.return_value = {'delete': mock_delete_func}
        
        # Run command
        delete(dbt_project_dir='/dbt')
        
        # Verify delete connector was called
        mock_delete_func.assert_called_once()
        call_args = mock_delete_func.call_args
        delete_map = call_args[0][0]
        
        # Verify delete map structure
        assert 'model.project.old_model' in delete_map
        assert delete_map['model.project.old_model']['table_id'] == 'my_db.my_schema.old_model'
        
        # Verify success exit
        mock_exit.assert_called_with(0)
    
    @patch('src.commands.delete.CacheManager')
    @patch('src.commands.delete.DbtGraph')
    @patch('src.commands.delete.get_connector')
    @patch('src.commands.delete.get_node_ids_from_structured_nodes')
    @patch('src.commands.delete.get_nodes')
    @patch('src.commands.delete.click.secho')
    @patch('src.commands.delete.click.echo')
    @patch('src.commands.delete.sys.exit')
    def test_delete_dry_run(
        self,
        mock_exit,
        mock_echo,
        mock_secho,
        mock_get_nodes_util,
        mock_get_node_ids,
        mock_get_connector,
        mock_graph,
        mock_vars,
        mock_cache
    ):
        """Test delete command in dry run mode."""
        # Setup mocks
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = {
            "deleted_nodes": {"model": {"model.project.old_model": {}}}
        }
        mock_cache.return_value = mock_cache_instance
        
        mock_vars_instance = MagicMock()
        namespace = Namespace(
            dbt_project_dir='/dbt',
            dry_run=True,
            target_config={'type': 'bigquery'}
        )
        mock_vars_instance.to_namespace.return_value = namespace
        mock_vars.return_value = mock_vars_instance
        
        mock_get_node_ids.return_value = ['model.project.old_model']
        
        mock_get_nodes_util.return_value = {
            'model.project.old_model': {
                'resource_type': 'model',
                'name': 'old_model',
                'database': 'my_db',
                'schema': 'my_schema',
                'config': {}
            }
        }
        
        mock_graph_instance = MagicMock()
        mock_graph.return_value = mock_graph_instance
        
        mock_delete_func = MagicMock()
        mock_get_connector.return_value = {'delete': mock_delete_func}
        
        # Run command
        delete(dbt_project_dir='/dbt', dry_run=True)
        
        # Verify dry run message was shown
        mock_echo.assert_any_call("Dry run mode enabled - no actual deletions will be performed.")
    
    @patch('src.commands.delete.CacheManager')
    @patch('src.commands.delete.DbtGraph')
    @patch('src.commands.delete.get_connector')
    @patch('src.commands.delete.get_node_ids_from_structured_nodes')
    @patch('src.commands.delete.get_nodes')
    @patch('src.commands.delete.logger')
    @patch('src.commands.delete.click.secho')
    @patch('src.commands.delete.sys.exit')
    def test_delete_skips_incomplete_nodes(
        self,
        mock_exit,
        mock_secho,
        mock_logger,
        mock_get_nodes_util,
        mock_get_node_ids,
        mock_get_connector,
        mock_graph,
        mock_vars,
        mock_cache
    ):
        """Test delete command skips nodes with missing database/schema/name."""
        # Setup mocks
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = {
            "deleted_nodes": {"model": {"model.project.incomplete": {}}}
        }
        mock_cache.return_value = mock_cache_instance
        
        mock_vars_instance = MagicMock()
        namespace = Namespace(
            dbt_project_dir='/dbt',
            dry_run=False,
            target_config={'type': 'bigquery'}
        )
        mock_vars_instance.to_namespace.return_value = namespace
        mock_vars.return_value = mock_vars_instance
        
        mock_get_node_ids.return_value = ['model.project.incomplete']
        
        # Node with missing schema
        mock_get_nodes_util.return_value = {
            'model.project.incomplete': {
                'resource_type': 'model',
                'name': 'incomplete',
                'database': 'my_db',
                'schema': None,
                'config': {}
            }
        }
        
        mock_graph_instance = MagicMock()
        mock_graph.return_value = mock_graph_instance
        
        mock_delete_func = MagicMock()
        mock_get_connector.return_value = {'delete': mock_delete_func}
        
        # Run command
        delete(dbt_project_dir='/dbt')
        
        # Verify warning was logged
        mock_logger.warning.assert_called_once()
        assert 'Missing database, schema or name' in str(mock_logger.warning.call_args)
        
        # Verify delete was still called (even with empty map)
        mock_delete_func.assert_called_once()
