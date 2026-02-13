"""Unit tests for the migration command."""
import pytest
from unittest.mock import MagicMock, patch
from argparse import Namespace
from src.commands.migration import migration


class TestMigrationCommand:
    """Test the migration command."""
    
    @patch('src.commands.migration.DbtGraph')
    @patch('src.commands.migration.CacheManager')
    @patch('src.commands.migration.Variables')
    @patch('src.commands.migration.logger')
    @patch('src.commands.migration.click.secho')
    def test_migration_no_cache(
        self,
        mock_secho,
        mock_logger,
        mock_vars,
        mock_cache,
        mock_graph
    ):
        """Test migration command exits when no cache is found."""
        # Setup mocks
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = None
        mock_cache.return_value = mock_cache_instance
        
        mock_vars_instance = MagicMock()
        mock_vars_instance.to_namespace.return_value = Namespace(
            dbt_project_dir='/dbt',
            reference_state='/dbt/.dbtstate',
            runner='local',
            target_config={'type': 'bigquery'}
        )
        mock_vars.return_value = mock_vars_instance
        
        mock_graph_instance = MagicMock()
        mock_graph.return_value = mock_graph_instance
        
        # Run command - expect SystemExit(1)
        with pytest.raises(SystemExit) as exc_info:
            migration(dbt_project_dir='/dbt', reference_state='/dbt/.dbtstate')
        
        assert exc_info.value.code == 1
    
    @patch('src.commands.migration.CacheManager')
    @patch('src.commands.migration.Variables')
    @patch('src.commands.migration.DbtGraph')
    @patch('src.commands.migration.get_connector')
    @patch('src.commands.migration.logger')
    @patch('src.commands.migration.click.secho')
    @patch('src.commands.migration.sys.exit')
    def test_migration_unsupported_connector(
        self,
        mock_exit,
        mock_secho,
        mock_logger,
        mock_get_connector,
        mock_graph,
        mock_vars,
        mock_cache
    ):
        """Test migration command with unsupported connector."""
        # Setup mocks
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = {
            "modified_nodes": {}
        }
        mock_cache.return_value = mock_cache_instance
        
        mock_vars_instance = MagicMock()
        mock_vars_instance.to_namespace.return_value = Namespace(
            dbt_project_dir='/dbt',
            target_config={'type': 'unsupported'}
        )
        mock_vars.return_value = mock_vars_instance
        
        mock_get_connector.return_value = {'migration': None}
        
        # Run command
        migration(dbt_project_dir='/dbt')
        
        # Verify error was logged
        mock_logger.error.assert_called_once()
        assert 'does not support migration strategy' in str(mock_logger.error.call_args)
        
        # Verify exit with error
        mock_exit.assert_called_with(1)
    
    @patch('src.commands.migration.CacheManager')
    @patch('src.commands.migration.Variables')
    @patch('src.commands.migration.DbtGraph')
    @patch('src.commands.migration.get_connector')
    @patch('src.commands.migration.get_node_ids_from_structured_nodes')
    @patch('src.commands.migration.filter_node_ids_by_type')
    @patch('src.commands.migration.logger')
    @patch('src.commands.migration.click.secho')
    @patch('src.commands.migration.click.echo')
    def test_migration_no_modified_models(
        self,
        mock_echo,
        mock_secho,
        mock_logger,
        mock_filter,
        mock_get_node_ids,
        mock_get_connector,
        mock_graph,
        mock_vars,
        mock_cache
    ):
        """Test migration command when no modified models are found."""
        # Setup mocks
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = {
            "modified_nodes": None
        }
        mock_cache.return_value = mock_cache_instance
        
        mock_vars_instance = MagicMock()
        mock_vars_instance.to_namespace.return_value = Namespace(
            dbt_project_dir='/dbt',
            reference_state='/dbt/.dbtstate',
            runner='local',
            target_config={'type': 'bigquery'}
        )
        mock_vars.return_value = mock_vars_instance
        
        mock_get_connector.return_value = {'migration': MagicMock()}
        mock_get_node_ids.return_value = []
        mock_filter.return_value = []
        
        mock_graph_instance = MagicMock()
        mock_graph.return_value = mock_graph_instance
        
        # Run command - expect SystemExit(0)
        with pytest.raises(SystemExit) as exc_info:
            migration(dbt_project_dir='/dbt', reference_state='/dbt/.dbtstate')
        
        assert exc_info.value.code == 0
    
    @patch('src.commands.migration.CacheManager')
    @patch('src.commands.migration.Variables')
    @patch('src.commands.migration.DbtGraph')
    @patch('src.commands.migration.get_connector')
    @patch('src.commands.migration.get_node_ids_from_structured_nodes')
    @patch('src.commands.migration.filter_node_ids_by_type')
    @patch('src.commands.migration.get_nodes')
    @patch('src.commands.migration.logger')
    @patch('src.commands.migration.click.secho')
    @patch('src.commands.migration.click.echo')
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
        mock_vars,
        mock_cache
    ):
        """Test migration command with modified models."""
        # Setup mocks
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = {
            "modified_nodes": {"model": {"model.project.model1": {}}}
        }
        mock_cache.return_value = mock_cache_instance
        
        mock_vars_instance = MagicMock()
        namespace = Namespace(
            dbt_project_dir='/dbt',
            reference_state='/dbt/.dbtstate',
            runner='local',
            target_config={'type': 'bigquery'}
        )
        mock_vars_instance.to_namespace.return_value = namespace
        mock_vars.return_value = mock_vars_instance
        
        mock_get_node_ids.return_value = ['model.project.model1']
        mock_filter.return_value = ['model.project.model1']
        
        mock_get_nodes_util.return_value = {
            'model.project.model1': {
                'id': 'model.project.model1',
                'resource_type': 'model',
                'name': 'model1',
                'database': 'my_db',
                'schema': 'my_schema',
                'config': {
                    'partition_by': {'field': 'date', 'data_type': 'date'}
                },
                'compiled_code': 'SELECT * FROM table'
            }
        }
        
        mock_graph_instance = MagicMock()
        mock_graph_instance.to_dict.return_value = {
            "model": {
                "model.project.model1": {
                    'config': {
                        'partition_by': {'field': 'date', 'data_type': 'date'}
                    }
                }
            }
        }
        mock_graph.return_value = mock_graph_instance
        
        mock_migration_func = MagicMock()
        mock_get_connector.return_value = {'migration': mock_migration_func}
        
        # Run command - expect SystemExit(0) after completion
        with pytest.raises(SystemExit) as exc_info:
            migration(dbt_project_dir='/dbt', reference_state='/dbt/.dbtstate')
        
        # Command may exit with 0 if no migrations needed
        assert exc_info.value.code == 0
    
    @patch('src.commands.migration.CacheManager')
    @patch('src.commands.migration.Variables')
    @patch('src.commands.migration.DbtGraph')
    @patch('src.commands.migration.get_connector')
    @patch('src.commands.migration.get_node_ids_from_structured_nodes')
    @patch('src.commands.migration.filter_node_ids_by_type')
    @patch('src.commands.migration.get_nodes')
    @patch('src.commands.migration.logger')
    @patch('src.commands.migration.click.secho')
    @patch('src.commands.migration.click.echo')
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
        mock_vars,
        mock_cache
    ):
        """Test migration command when partitioning hasn't changed."""
        # Setup mocks
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = {
            "modified_nodes": {"model": {"model.project.model1": {}}}
        }
        mock_cache.return_value = mock_cache_instance
        
        mock_vars_instance = MagicMock()
        namespace = Namespace(
            dbt_project_dir='/dbt',
            reference_state='/dbt/.dbtstate',
            runner='local',
            target_config={'type': 'bigquery'}
        )
        mock_vars_instance.to_namespace.return_value = namespace
        mock_vars.return_value = mock_vars_instance
        
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
        mock_get_connector.return_value = {'migration': mock_migration_func}
        
        # Run command - expect SystemExit(0)
        with pytest.raises(SystemExit) as exc_info:
            migration(dbt_project_dir='/dbt', reference_state='/dbt/.dbtstate')
        
        assert exc_info.value.code == 0
