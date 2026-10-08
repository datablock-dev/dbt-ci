"""Unit tests for the delete command."""
import pytest
from unittest.mock import MagicMock, patch
from argparse import Namespace
from dbt_ci.commands.delete.index import delete as index


class TestDeleteCommand:
    """Test the delete command."""
    
    @patch('dbt_ci.commands.delete.index.get_profile')
    @patch('dbt_ci.commands.delete.index.DbtGraph')
    @patch('dbt_ci.commands.delete.index.CacheManager')
    @patch('dbt_ci.commands.delete.index.click.secho')
    @patch('dbt_ci.commands.delete.index.sys.exit')
    @patch('dbt_ci.commands.delete.index.logger')
    @patch('dbt_ci.commands.delete.index.click.echo')
    def test_delete_no_cache(
        self,
        mock_echo,
        mock_logger,
        mock_exit,
        mock_secho,
        mock_cache,
        mock_graph,
        mock_get_profile
    ):
        """Test delete command exits when no cache is found."""
        # Setup mocks
        mock_get_profile.return_value = {"type": "bigquery"}
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
        )
        index(args)
        
        # A missing cache means init never ran, which must fail the step
        mock_exit.assert_called_with(1)
        assert "No cache found" in mock_logger.error.call_args[0][0]
    
    @patch('dbt_ci.commands.delete.index.get_profile')
    @patch('dbt_ci.commands.delete.index.CacheManager')
    @patch('dbt_ci.commands.delete.index.DbtGraph')
    @patch('dbt_ci.commands.delete.index.get_connector')
    @patch('dbt_ci.commands.delete.index.get_node_ids_from_structured_nodes')
    @patch('dbt_ci.commands.delete.index.click.secho')
    @patch('dbt_ci.commands.delete.index.sys.exit')
    @patch('dbt_ci.commands.delete.index.logger')
    @patch('dbt_ci.commands.delete.index.click.echo')
    def test_delete_no_deleted_nodes(
        self,
        mock_echo,
        mock_logger,
        mock_exit,
        mock_secho,
        mock_get_nodes,
        mock_get_connector,
        mock_graph,
        mock_cache,
        mock_get_profile
    ):
        """Test delete command when no deleted nodes are found."""
        # Setup mocks
        mock_get_profile.return_value = {"type": "bigquery"}
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = {
            "deleted_nodes": None
        }
        mock_cache.return_value = mock_cache_instance
        mock_get_nodes.return_value = []
        
        # Run command
        args = Namespace(
            dbt_project_dir='/dbt',
            dry_run=False
        )
        index(args)
        
        # Verify appropriate message was shown
        mock_logger.info.assert_any_call("No deleted nodes found in cache, skipping...")
    
    @patch('dbt_ci.commands.delete.index.get_profile')
    @patch('dbt_ci.commands.delete.index.CacheManager')
    @patch('dbt_ci.commands.delete.index.DbtGraph')
    @patch('dbt_ci.commands.delete.index.get_connector')
    @patch('dbt_ci.commands.delete.index.get_node_ids_from_structured_nodes')
    @patch('dbt_ci.commands.delete.index.get_nodes')
    @patch('dbt_ci.commands.delete.index.click.secho')
    @patch('dbt_ci.commands.delete.index.click.echo')
    @patch('dbt_ci.commands.delete.index.sys.exit')
    def test_delete_with_deleted_nodes(
        self,
        mock_exit,
        mock_echo,
        mock_secho,
        mock_get_nodes_util,
        mock_get_node_ids,
        mock_get_connector,
        mock_graph,
        mock_cache,
        mock_get_profile
    ):
        """Test delete command with deleted nodes."""
        # Setup mocks
        mock_get_profile.return_value = {"type": "bigquery"}
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = {
            "deleted_nodes": {"model": {"model.project.old_model": {}}}
        }
        mock_cache.return_value = mock_cache_instance
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
        mock_get_connector.return_value = {'strategies': {'delete': mock_delete_func}}
        
        # Run command
        args = Namespace(
            dbt_project_dir='/dbt',
            dry_run=False
        )
        index(args)
        
        # Verify delete connector was called
        mock_delete_func.assert_called_once()
        call_args = mock_delete_func.call_args
        delete_map = call_args[0][0]
        
        # Verify delete map structure
        assert 'model.project.old_model' in delete_map
        assert delete_map['model.project.old_model']['table_id'] == 'my_db.my_schema.old_model'
        
        # Verify success exit
        mock_exit.assert_called_with(0)
    
    @patch('dbt_ci.commands.delete.index.get_profile')
    @patch('dbt_ci.commands.delete.index.CacheManager')
    @patch('dbt_ci.commands.delete.index.DbtGraph')
    @patch('dbt_ci.commands.delete.index.get_connector')
    @patch('dbt_ci.commands.delete.index.get_node_ids_from_structured_nodes')
    @patch('dbt_ci.commands.delete.index.get_nodes')
    @patch('dbt_ci.commands.delete.index.click.secho')
    @patch('dbt_ci.commands.delete.index.click.echo')
    @patch('dbt_ci.commands.delete.index.sys.exit')
    @patch('dbt_ci.commands.delete.index.logger')
    def test_delete_dry_run(
        self,
        mock_logger,
        mock_exit,
        mock_echo,
        mock_secho,
        mock_get_nodes_util,
        mock_get_node_ids,
        mock_get_connector,
        mock_graph,
        mock_cache,
        mock_get_profile
    ):
        """Test delete command in dry run mode."""
        # Setup mocks
        mock_get_profile.return_value = {"type": "bigquery"}
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = {
            "deleted_nodes": {"model": {"model.project.old_model": {}}}
        }
        mock_cache.return_value = mock_cache_instance
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
        mock_get_connector.return_value = {'strategies': {'delete': mock_delete_func}}
        
        # Run command
        args = Namespace(
            dbt_project_dir='/dbt',
            dry_run=True
        )
        index(args)
        
        # Verify dry run message was shown
        mock_logger.info.assert_any_call("Dry run mode enabled - no actual deletions will be performed.")
    
    @patch('dbt_ci.commands.delete.index.get_profile')
    @patch('dbt_ci.commands.delete.index.CacheManager')
    @patch('dbt_ci.commands.delete.index.DbtGraph')
    @patch('dbt_ci.commands.delete.index.get_connector')
    @patch('dbt_ci.commands.delete.index.get_node_ids_from_structured_nodes')
    @patch('dbt_ci.commands.delete.index.get_nodes')
    @patch('dbt_ci.commands.delete.index.logger')
    @patch('dbt_ci.commands.delete.index.click.secho')
    @patch('dbt_ci.commands.delete.index.sys.exit')
    def test_delete_skips_incomplete_nodes(
        self,
        mock_exit,
        mock_secho,
        mock_logger,
        mock_get_nodes_util,
        mock_get_node_ids,
        mock_get_connector,
        mock_graph,
        mock_cache,
        mock_get_profile
    ):
        """Test delete command skips nodes with missing database/schema/name."""
        # Setup mocks
        mock_get_profile.return_value = {"type": "bigquery"}
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = {
            "deleted_nodes": {"model": {"model.project.incomplete": {}}}
        }
        mock_cache.return_value = mock_cache_instance
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
        mock_get_connector.return_value = {'strategies': {'delete': mock_delete_func}}
        
        # Run command
        args = Namespace(
            dbt_project_dir='/dbt',
            dry_run=False
        )
        index(args)
        
        # Verify warning was logged
        mock_logger.warning.assert_called_once()
        assert 'Missing database, schema or name' in str(mock_logger.warning.call_args)
        
        # Verify delete was still called (even with empty map)
        mock_delete_func.assert_called_once()


def _graph(*nodes: dict) -> dict:
    """Build a minimal dependency graph with the given model nodes."""
    graph = {key: {} for key in ("model", "seed", "snapshot", "test", "macro", "exposure", "source")}
    for node in nodes:
        graph["model"][node["id"]] = {"resource_type": "model", "config": {}, **node}
    return graph


class TestDeleteSafeguards:
    """Test that delete never drops a relation the target project still uses."""

    PROD_ORDERS = {"id": "model.pkg.orders", "name": "orders", "database": "proj", "schema": "analytics"}

    def build(self, reference: dict, target: dict | None, deleted: list[str]):
        """Run generate_delete_map against the given reference and target graphs."""
        from dbt_ci.commands.delete.index import generate_delete_map

        cache = MagicMock()
        cache.get_cache.side_effect = lambda name="cache.json", *_: (
            {"deleted_nodes": {}} if name == "cache.json"
            else (target if name == "target_manifest.json" else {})
        )

        def make_graph(_args, is_reference=False):
            """Return the reference or target graph depending on the flag."""
            graph = MagicMock()
            graph.to_dict.return_value = reference if is_reference else target
            return graph

        with patch("dbt_ci.commands.delete.index.DbtGraph", side_effect=make_graph), \
             patch("dbt_ci.commands.delete.index.get_node_ids_from_structured_nodes", return_value=deleted), \
             patch("dbt_ci.commands.delete.index.click.secho"):
            return generate_delete_map(Namespace(dry_run=False), cache)

    def test_truly_deleted_model_is_dropped(self):
        """A model missing from the target project is still deleted."""
        delete_map = self.build(_graph(self.PROD_ORDERS), _graph(), ["model.pkg.orders"])
        assert delete_map["model.pkg.orders"]["table_id"] == "proj.analytics.orders"

    def test_moved_model_is_kept(self):
        """A moved file keeps its unique_id, so its live table must not be dropped."""
        delete_map = self.build(_graph(self.PROD_ORDERS), _graph(self.PROD_ORDERS), ["model.pkg.orders"])
        assert delete_map == {}

    def test_relation_reused_by_another_model_is_kept(self):
        """A table now produced by a different node (e.g. via an alias) is not dropped."""
        replacement = {"id": "model.pkg.orders_v2", "name": "orders_v2", "database": "proj",
                       "schema": "analytics", "config": {"alias": "orders"}}
        delete_map = self.build(_graph(self.PROD_ORDERS), _graph(replacement), ["model.pkg.orders"])
        assert delete_map == {}

    def test_missing_target_manifest_fails(self):
        """Without the target manifest deletions cannot be verified, so nothing is dropped."""
        with pytest.raises(RuntimeError, match="No target manifest"):
            self.build(_graph(self.PROD_ORDERS), None, ["model.pkg.orders"])
