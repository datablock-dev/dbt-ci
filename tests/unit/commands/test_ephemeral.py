"""Unit tests for the ephemeral command."""
import pytest
from unittest.mock import MagicMock, patch
from argparse import Namespace
from src.commands.ephemeral import ephemeral


class TestEphemeralCommand:
    """Test the ephemeral command."""
    
    @patch('src.commands.ephemeral.get_profile')
    @patch('src.commands.ephemeral.DbtGraph')
    @patch('src.commands.ephemeral.CacheManager')
    @patch('src.commands.ephemeral.click.secho')
    @patch('src.commands.ephemeral.click.echo')
    def test_ephemeral_no_cache(
        self,
        mock_echo,
        mock_secho,
        mock_cache,
        mock_graph,
        mock_get_profile
    ):
        """Test ephemeral command exits when no cache is found."""
        # Setup mocks
        mock_get_profile.return_value = {"type": "bigquery"}
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = None
        mock_cache.return_value = mock_cache_instance
        mock_graph_instance = MagicMock()
        mock_graph.return_value = mock_graph_instance
        
        # Run command - expect SystemExit(1) since no cache is an error
        args = Namespace(
            dbt_project_dir='/dbt',
            reference_state='/dbt/.dbtstate',
            dry_run=False
        )
        with pytest.raises(SystemExit) as exc_info:
            ephemeral(args)
        
        assert exc_info.value.code == 1
    
    @patch('src.commands.ephemeral.get_profile')
    @patch('src.commands.ephemeral.DbtGraph')
    @patch('src.commands.ephemeral.CacheManager')
    @patch('src.commands.ephemeral.get_node_ids_from_structured_nodes')
    @patch('src.commands.ephemeral.click.secho')
    @patch('src.commands.ephemeral.click.echo')
    def test_ephemeral_no_modified_nodes(
        self,
        mock_echo,
        mock_secho,
        mock_get_nodes,
        mock_cache,
        mock_graph,
        mock_get_profile
    ):
        """Test ephemeral command when no modified nodes are found."""
        # Setup mocks
        mock_get_profile.return_value = {"type": "bigquery"}
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = {
            "modified_nodes": None,
            "new_nodes": None
        }
        mock_cache.return_value = mock_cache_instance
        mock_get_nodes.return_value = []
        
        mock_graph_instance = MagicMock()
        mock_graph.return_value = mock_graph_instance
        
        # Run command - expect SystemExit(0)
        args = Namespace(
            dbt_project_dir='/dbt',
            reference_state='/dbt/.dbtstate',
            dry_run=False
        )
        with pytest.raises(SystemExit) as exc_info:
            ephemeral(args)
        
        assert exc_info.value.code == 0
    
    @patch('src.commands.ephemeral.get_profile')
    @patch('src.commands.ephemeral.CacheManager')
    @patch('src.commands.ephemeral.DbtGraph')
    @patch('src.commands.ephemeral.DB_CONNECTORS', {'bigquery': 'bigquery'})
    @patch('src.commands.ephemeral.get_connector')
    @patch('src.commands.ephemeral.get_node_ids_from_structured_nodes')
    @patch('src.commands.ephemeral.get_nodes')
    @patch('src.commands.ephemeral.get_downstream_dependencies')
    @patch('src.commands.ephemeral.click.secho')
    @patch('src.commands.ephemeral.click.echo')
    @patch('src.commands.ephemeral.sys.exit')
    def test_ephemeral_with_modified_nodes(
        self,
        mock_exit,
        mock_echo,
        mock_secho,
        mock_downstream,
        mock_get_nodes_util,
        mock_get_node_ids,
        mock_get_connector,
        mock_graph,
        mock_cache,
        mock_get_profile
    ):
        """Test ephemeral command with modified nodes."""
        # Setup mocks
        mock_get_profile.return_value = {"type": "bigquery"}
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = {
            "modified_nodes": {"model": {"model.project.model1": {}}},
            "new_nodes": {"model": {"model.project.model2": {}}}
        }
        mock_cache.return_value = mock_cache_instance
        mock_get_node_ids.side_effect = [
            ['model.project.model1'],  # modified
            ['model.project.model2']   # new
        ]
        
        mock_get_nodes_util.return_value = {
            'model.project.model1': {
                'resource_type': 'model',
                'name': 'model1',
                'database': 'my_db',
                'schema': 'my_schema',
                'materialized': 'table',
                'config': {}
            }
        }
        
        mock_downstream.return_value = []
        
        mock_graph_instance = MagicMock()
        mock_graph_instance.to_dict.return_value = {}
        mock_graph.return_value = mock_graph_instance
        
        mock_ephemeral_func = MagicMock()
        mock_connector = MagicMock()
        mock_connector.ephemeral = mock_ephemeral_func
        mock_get_connector.return_value = mock_connector
        
        # Run command
        args = Namespace(
            dbt_project_dir='/dbt',
            reference_state='/dbt/.dbtstate',
            dry_run=False
        )
        ephemeral(args)
        
        # Verify ephemeral connector was called
        mock_ephemeral_func.assert_called_once()
        
        # Verify success exit
        mock_exit.assert_called_with(0)
    
    @patch('src.commands.ephemeral.get_profile')
    @patch('src.commands.ephemeral.CacheManager')
    @patch('src.commands.ephemeral.DbtGraph')
    @patch('src.commands.ephemeral.DB_CONNECTORS', {})
    @patch('src.commands.ephemeral.get_node_ids_from_structured_nodes')
    @patch('src.commands.ephemeral.logger')
    @patch('src.commands.ephemeral.click.secho')
    @patch('src.commands.ephemeral.sys.exit')
    def test_ephemeral_unsupported_connector(
        self,
        mock_exit,
        mock_secho,
        mock_logger,
        mock_get_node_ids,
        mock_graph,
        mock_cache,
        mock_get_profile
    ):
        """Test ephemeral command with unsupported connector."""
        # Setup mocks
        mock_get_profile.return_value = {"type": "bigquery"}
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = {
            "modified_nodes": {"model": {"model.project.model1": {}}},
            "new_nodes": None
        }
        mock_cache.return_value = mock_cache_instance
        mock_get_node_ids.return_value = ['model.project.model1']
        
        # Run command
        args = Namespace(
            dbt_project_dir='/dbt',
            dry_run=False
        )
        ephemeral(args)
        
        # Verify error was logged
        mock_logger.error.assert_called_once()
        assert 'Unsupported' in str(mock_logger.error.call_args)
        
        # Verify exit with error
        mock_exit.assert_called_with(1)
    
    @patch('src.commands.ephemeral.get_profile')
    @patch('src.commands.ephemeral.CacheManager')
    @patch('src.commands.ephemeral.DbtGraph')
    @patch('src.commands.ephemeral.DB_CONNECTORS', {'bigquery': 'bigquery'})
    @patch('src.commands.ephemeral.get_connector')
    @patch('src.commands.ephemeral.get_node_ids_from_structured_nodes')
    @patch('src.commands.ephemeral.get_nodes')
    @patch('src.commands.ephemeral.get_downstream_dependencies')
    @patch('src.commands.ephemeral.click.secho')
    @patch('src.commands.ephemeral.click.echo')
    def test_ephemeral_dry_run(
        self,
        mock_echo,
        mock_secho,
        mock_downstream,
        mock_get_nodes_util,
        mock_get_node_ids,
        mock_get_connector,
        mock_graph,
        mock_cache,
        mock_get_profile
    ):
        """Test ephemeral command in dry run mode."""
        # Setup mocks
        mock_get_profile.return_value = {"type": "bigquery"}
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = {
            "modified_nodes": {"model": {"model.project.model1": {}}},
            "new_nodes": None
        }
        mock_cache.return_value = mock_cache_instance
        mock_get_node_ids.return_value = ['model.project.model1']
        
        mock_get_nodes_util.return_value = {
            'model.project.model1': {
                'resource_type': 'model',
                'name': 'model1',
                'database': 'my_db',
                'schema': 'my_schema',
                'materialized': 'table',
                'config': {}
            }
        }
        
        mock_downstream.return_value = []
        
        mock_graph_instance = MagicMock()
        mock_graph.return_value = mock_graph_instance
        
        # Run command - expect SystemExit(0)
        args = Namespace(
            dbt_project_dir='/dbt',
            reference_state='/dbt/.dbtstate',
            dry_run=True
        )
        with pytest.raises(SystemExit) as exc_info:
            ephemeral(args)
        
        assert exc_info.value.code == 0
