"""Unit tests for the migration command."""
import pytest
from unittest.mock import MagicMock, patch
from argparse import Namespace
from src.commands.migration.index import migration as index


class TestMigrationCommand:
    """Test the migration command."""
    
    @patch('src.commands.migration.index.get_profile')
    @patch('src.commands.migration.index.DbtGraph')
    @patch('src.commands.migration.index.CacheManager')
    @patch('src.commands.migration.index.logger')
    @patch('src.commands.migration.index.click.secho')
    def test_migration_no_cache(
        self,
        mock_secho,
        mock_logger,
        mock_cache,
        mock_graph,
        mock_get_profile
    ):
        """Test migration command exits when no cache is found."""
        # Setup mocks
        mock_get_profile.return_value = {"type": "bigquery"}
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = None
        mock_cache.return_value = mock_cache_instance
        mock_graph_instance = MagicMock()
        mock_graph.return_value = mock_graph_instance
        
        # Run command - expect SystemExit(1)
        args = Namespace(
            dbt_project_dir='/dbt',
            reference_state='/dbt/.dbtstate',
            dry_run=False
        )
        with pytest.raises(SystemExit) as exc_info:
            index(args)
        
        assert exc_info.value.code == 1
    
    @patch('src.commands.migration.index.get_profile')
    @patch('src.commands.migration.index.CacheManager')
    @patch('src.commands.migration.index.DbtGraph')
    @patch('src.commands.migration.index.get_connector')
    @patch('src.commands.migration.index.logger')
    @patch('src.commands.migration.index.click.secho')
    @patch('src.commands.migration.index.sys.exit')
    def test_migration_unsupported_connector(
        self,
        mock_exit,
        mock_secho,
        mock_logger,
        mock_get_connector,
        mock_graph,
        mock_cache,
        mock_get_profile
    ):
        """Test migration command with unsupported connector."""
        # Setup mocks
        mock_get_profile.return_value = {"type": "bigquery"}
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = {
            "modified_nodes": {}
        }
        mock_cache.return_value = mock_cache_instance
        mock_get_connector.return_value = {'strategies': {'migration': None}}
        
        # Run command
        args = Namespace(
            dbt_project_dir='/dbt',
            dry_run=False
        )
        index(args)
        
        # Verify error was logged
        mock_logger.error.assert_called_once()
        assert 'does not have a migration strategy' in str(mock_logger.error.call_args)
        
        # Verify exit with error
        mock_exit.assert_called_with(1)
    
    @patch('src.commands.migration.index.get_profile')
    @patch('src.commands.migration.index.CacheManager')
    @patch('src.commands.migration.index.DbtGraph')
    @patch('src.commands.migration.index.get_connector')
    @patch('src.commands.migration.index.get_node_ids_from_structured_nodes')
    @patch('src.commands.migration.index.filter_node_ids_by_multiple_types')
    @patch('src.commands.migration.index.logger')
    @patch('src.commands.migration.index.click.secho')
    @patch('src.commands.migration.index.click.echo')
    def test_migration_no_modified_models(
        self,
        mock_echo,
        mock_secho,
        mock_logger,
        mock_filter,
        mock_get_node_ids,
        mock_get_connector,
        mock_graph,
        mock_cache,
        mock_get_profile
    ):
        """Test migration command when no modified models are found."""
        # Setup mocks
        mock_get_profile.return_value = {"type": "bigquery"}
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = {
            "modified_nodes": None
        }
        mock_cache.return_value = mock_cache_instance
        mock_get_connector.return_value = {'strategies': {'migration': MagicMock()}}
        mock_get_node_ids.return_value = []
        mock_filter.return_value = []
        
        mock_graph_instance = MagicMock()
        mock_graph.return_value = mock_graph_instance
        
        # Run command - expect SystemExit(0)
        args = Namespace(
            dbt_project_dir='/dbt',
            reference_state='/dbt/.dbtstate',
            dry_run=False
        )
        with pytest.raises(SystemExit) as exc_info:
            index(args)
        
        assert exc_info.value.code == 0
    
    @patch('src.commands.migration.index.get_profile')
    @patch('src.commands.migration.index.CacheManager')
    @patch('src.commands.migration.index.DbtGraph')
    @patch('src.commands.migration.index.get_connector')
    @patch('src.commands.migration.index.get_node_ids_from_structured_nodes')
    @patch('src.commands.migration.index.filter_node_ids_by_multiple_types')
    @patch('src.commands.migration.index.get_nodes')
    @patch('src.commands.migration.index.logger')
    @patch('src.commands.migration.index.click.secho')
    @patch('src.commands.migration.index.click.echo')
    def test_migration_with_modified_models(
        self,
        mock_echo,
        mock_secho,
        mock_logger,
        mock_get_nodes_util,
        mock_filter,
        mock_get_node_ids,
        mock_get_connector,
        mock_graph,
        mock_cache,
        mock_get_profile
    ):
        """Test migration command with modified models."""
        # Setup mocks
        mock_get_profile.return_value = {"type": "bigquery"}
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = {
            "modified_nodes": {"model": {"model.project.model1": {}}}
        }
        mock_cache.return_value = mock_cache_instance
        mock_get_node_ids.return_value = ['model.project.model1']
        mock_filter.return_value = ['model.project.model1']
        
        # Target node with new partitioning and incremental materialization
        target_nodes = {
            'model.project.model1': {
                'id': 'model.project.model1',
                'resource_type': 'model',
                'name': 'model1',
                'database': 'my_db',
                'schema': 'my_schema',
                'config': {
                    'materialized': 'incremental',
                    'partition_by': {'field': 'new_date', 'data_type': 'date'}
                },
                'compiled_code': 'SELECT * FROM table'
            }
        }
        
        # Reference node with old partitioning
        reference_nodes = {
            'model.project.model1': {
                'id': 'model.project.model1',
                'resource_type': 'model',
                'name': 'model1',
                'database': 'my_db',
                'schema': 'my_schema',
                'config': {
                    'materialized': 'incremental',
                    'partition_by': {'field': 'old_date', 'data_type': 'date'}
                },
                'compiled_code': 'SELECT * FROM table'
            }
        }
        
        # get_nodes is called twice: once for target, once for reference
        mock_get_nodes_util.side_effect = [target_nodes, reference_nodes]
        
        # Graph to_dict returns are not directly used since get_nodes is mocked
        mock_graph_instance = MagicMock()
        mock_graph.return_value = mock_graph_instance
        
        mock_migration_func = MagicMock()
        mock_get_connector.return_value = {'strategies': {'migration': mock_migration_func}}
        
        # Run command - migration should complete successfully without sys.exit()
        args = Namespace(
            dbt_project_dir='/dbt',
            reference_state='/dbt/.dbtstate',
            dry_run=False
        )
        index(args)
        
        # Verify migration function was called with correct migration map
        mock_migration_func.assert_called_once()
        call_args = mock_migration_func.call_args[0]
        migration_map = call_args[0]
        
        # Verify migration map structure
        assert migration_map['connector'] == 'bigquery'
        assert 'model.project.model1' in migration_map['nodes']
        assert migration_map['nodes']['model.project.model1']['table_id'] == 'my_db.my_schema.model1'
        assert migration_map['nodes']['model.project.model1']['old_partitioning'] == {'field': 'old_date', 'data_type': 'date'}
        assert migration_map['nodes']['model.project.model1']['new_partitioning'] == {'field': 'new_date', 'data_type': 'date'}
    
    @patch('src.commands.migration.index.get_profile')
    @patch('src.commands.migration.index.CacheManager')
    @patch('src.commands.migration.index.DbtGraph')
    @patch('src.commands.migration.index.get_connector')
    @patch('src.commands.migration.index.get_node_ids_from_structured_nodes')
    @patch('src.commands.migration.index.filter_node_ids_by_multiple_types')
    @patch('src.commands.migration.index.get_nodes')
    @patch('src.commands.migration.index.logger')
    @patch('src.commands.migration.index.click.secho')
    @patch('src.commands.migration.index.click.echo')
    def test_migration_no_partitioning_changes(
        self,
        mock_echo,
        mock_secho,
        mock_logger,
        mock_get_nodes_util,
        mock_filter,
        mock_get_node_ids,
        mock_get_connector,
        mock_graph,
        mock_cache,
        mock_get_profile
    ):
        """Test migration command when partitioning hasn't changed."""
        # Setup mocks
        mock_get_profile.return_value = {"type": "bigquery"}
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = {
            "modified_nodes": {"model": {"model.project.model1": {}}}
        }
        mock_cache.return_value = mock_cache_instance
        mock_get_node_ids.return_value = ['model.project.model1']
        mock_filter.return_value = ['model.project.model1']
        
        # Same partitioning in both reference and target
        partitioning = {'field': 'date', 'data_type': 'date'}
        
        mock_get_nodes_util.return_value = {
            'model.project.model1': {
                'id': 'model.project.model1',
                'resource_type': 'model',
                'name': 'model1',
                'config': {'partition_by': partitioning}
            }
        }
        
        mock_graph_instance = MagicMock()
        mock_graph_instance.to_dict.return_value = {
            "model": {
                "model.project.model1": {
                    'config': {'partition_by': partitioning}
                }
            }
        }
        mock_graph.return_value = mock_graph_instance
        
        mock_migration_func = MagicMock()
        mock_get_connector.return_value = {'strategies': {'migration': mock_migration_func}}
        
        # Run command - expect SystemExit(0)
        args = Namespace(
            dbt_project_dir='/dbt',
            reference_state='/dbt/.dbtstate',
            dry_run=False
        )
        with pytest.raises(SystemExit) as exc_info:
            index(args)
        
        assert exc_info.value.code == 0
