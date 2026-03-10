"""Unit tests for the ephemeral command."""
import pytest
from unittest.mock import MagicMock, patch
from argparse import Namespace
from dbt_ci.commands.ephemeral.index import ephemeral


class TestEphemeralCommand:
    """Test the ephemeral command."""
    
    @patch('dbt_ci.commands.ephemeral.index.get_profile')
    @patch('dbt_ci.commands.ephemeral.index.DbtGraph')
    @patch('dbt_ci.commands.ephemeral.index.CacheManager')
    @patch('dbt_ci.commands.ephemeral.index.click.secho')
    @patch('dbt_ci.commands.ephemeral.index.click.echo')
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
    
    @patch('dbt_ci.commands.ephemeral.index.get_profile')
    @patch('dbt_ci.commands.ephemeral.index.DbtGraph')
    @patch('dbt_ci.commands.ephemeral.index.CacheManager')
    @patch('dbt_ci.commands.ephemeral.index.get_node_ids_from_structured_nodes')
    @patch('dbt_ci.commands.ephemeral.index.click.secho')
    @patch('dbt_ci.commands.ephemeral.index.click.echo')
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
    
    @patch('dbt_ci.commands.ephemeral.index.get_profile')
    @patch('dbt_ci.commands.ephemeral.index.CacheManager')
    @patch('dbt_ci.commands.ephemeral.index.DbtGraph')
    @patch('dbt_ci.commands.ephemeral.index.DB_CONNECTORS', {'bigquery': 'bigquery'})
    @patch('dbt_ci.commands.ephemeral.index.clone_command')
    @patch('dbt_ci.commands.ephemeral.index.get_node_ids_from_structured_nodes')
    @patch('dbt_ci.commands.ephemeral.index.get_nodes')
    @patch('dbt_ci.commands.ephemeral.index.get_upstream_dependencies')
    @patch('dbt_ci.commands.ephemeral.index.get_downstream_dependencies')
    @patch('dbt_ci.commands.ephemeral.index.click.secho')
    @patch('dbt_ci.commands.ephemeral.index.click.echo')
    @patch('dbt_ci.commands.ephemeral.index.sys.exit')
    def test_ephemeral_with_modified_nodes(
        self,
        mock_exit,
        mock_echo,
        mock_secho,
        mock_downstream,
        mock_upstream,
        mock_get_nodes_util,
        mock_get_node_ids,
        mock_clone_command,
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
            ['model.project.model1'],  # modified_nodes
            [],                        # deleted_nodes
            ['model.project.model2']   # new_nodes
        ]
        
        mock_get_nodes_util.return_value = {
            'model.project.model1': {
                'resource_type': 'model',
                'name': 'model1',
                'database': 'my_db',
                'schema': 'my_schema',
                'materialized': 'incremental',
                'config': {}
            }
        }
        
        mock_downstream.return_value = []
        mock_upstream.return_value = []
        
        mock_graph_instance = MagicMock()
        mock_graph_instance.to_dict.return_value = {}
        mock_graph.return_value = mock_graph_instance
        
        # Run command
        args = Namespace(
            dbt_project_dir='/dbt',
            reference_state='/dbt/.dbtstate',
            dry_run=False
        )
        ephemeral(args)
        
        # Verify clone_command was called with the ephemeral map nodes
        mock_clone_command.assert_called_once()
        
        # Verify success exit
        mock_exit.assert_called_with(0)
    
    @patch('dbt_ci.commands.ephemeral.index.get_profile')
    @patch('dbt_ci.commands.ephemeral.index.CacheManager')
    @patch('dbt_ci.commands.ephemeral.index.DbtGraph')
    @patch('dbt_ci.commands.ephemeral.index.DB_CONNECTORS', {})
    @patch('dbt_ci.commands.ephemeral.index.get_node_ids_from_structured_nodes')
    @patch('dbt_ci.commands.ephemeral.index.logger')
    @patch('dbt_ci.commands.ephemeral.index.click.secho')
    @patch('dbt_ci.commands.ephemeral.index.sys.exit')
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
        
        # Verify error was logged (may be called more than once due to validation in sub-functions)
        mock_logger.error.assert_called()
        assert 'Unsupported' in str(mock_logger.error.call_args)
        
        # Verify exit with error
        mock_exit.assert_called_with(1)
    
    @patch('dbt_ci.commands.ephemeral.index.get_profile')
    @patch('dbt_ci.commands.ephemeral.index.CacheManager')
    @patch('dbt_ci.commands.ephemeral.index.DbtGraph')
    @patch('dbt_ci.commands.ephemeral.index.DB_CONNECTORS', {'bigquery': 'bigquery'})
    @patch('dbt_ci.commands.ephemeral.index.clone_command')
    @patch('dbt_ci.commands.ephemeral.index.get_node_ids_from_structured_nodes')
    @patch('dbt_ci.commands.ephemeral.index.get_nodes')
    @patch('dbt_ci.commands.ephemeral.index.get_upstream_dependencies')
    @patch('dbt_ci.commands.ephemeral.index.get_downstream_dependencies')
    @patch('dbt_ci.commands.ephemeral.index.click.secho')
    @patch('dbt_ci.commands.ephemeral.index.click.echo')
    def test_ephemeral_dry_run(
        self,
        mock_echo,
        mock_secho,
        mock_downstream,
        mock_upstream,
        mock_get_nodes_util,
        mock_get_node_ids,
        mock_clone_command,
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
        mock_upstream.return_value = []
        
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
