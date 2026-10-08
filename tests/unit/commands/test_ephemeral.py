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
    @patch('dbt_ci.commands.ephemeral.index.clone_command')
    def test_ephemeral_no_modified_nodes(
        self,
        mock_clone_command,
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
    @patch('dbt_ci.commands.ephemeral.index.get_node_ids_from_structured_nodes')
    @patch('dbt_ci.commands.ephemeral.index.click.secho')
    @patch('dbt_ci.commands.ephemeral.index.sys.exit')
    @patch('dbt_ci.commands.ephemeral.index.clone_command')
    def test_ephemeral_unsupported_connector(
        self,
        mock_clone_command,
        mock_exit,
        mock_secho,
        mock_get_node_ids,
        mock_graph,
        mock_cache,
        mock_get_profile
    ):
        """Test ephemeral command calls clone_command regardless of connector type."""
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

        # Connector type is no longer checked — clone_command is always invoked
        mock_clone_command.assert_called_once()

        # Verify success exit
        mock_exit.assert_called_with(0)
    
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


def _keep_all_node_ids(*args, **kwargs):
    """Stand in for filter_node_ids_by_type by keeping every node id."""
    node_ids = kwargs.get("node_ids", args[1] if len(args) > 1 else [])
    return list(node_ids)


class TestCloneCommand:
    """Test failure handling and the returned clone selection of clone_command."""

    def run_clone(self, returncode: int):
        """Invoke clone_command for one changed model with a stubbed dbt result."""
        from dbt_ci.commands.ephemeral.clone import clone_command

        result = MagicMock(returncode=returncode)
        with patch("dbt_ci.commands.ephemeral.clone.get_profile", return_value={"threads": 1}), \
             patch("dbt_ci.commands.ephemeral.clone.DbtGraph"), \
             patch("dbt_ci.commands.ephemeral.clone.get_downstream_dependencies", return_value={"model.pkg.child"}), \
             patch("dbt_ci.commands.ephemeral.clone.get_upstream_dependencies", return_value=None), \
             patch("dbt_ci.commands.ephemeral.clone.filter_node_ids_by_type", side_effect=_keep_all_node_ids), \
             patch("dbt_ci.commands.ephemeral.clone.get_selectors", return_value=["pkg.parent"]), \
             patch("dbt_ci.commands.ephemeral.clone.resolve_dbt_commands", return_value=["clone"]), \
             patch("dbt_ci.commands.ephemeral.clone.run_dbt_command", return_value=result):
            return clone_command(
                {"modified_nodes": ["model.pkg.parent"], "new_nodes": [], "deleted_nodes": []},
                Namespace(dry_run=False),
            )

    def test_failed_clone_exits_non_zero(self):
        """The in-process runner reports failures via returncode, which must fail the step."""
        with pytest.raises(SystemExit) as exc_info:
            self.run_clone(returncode=1)
        assert exc_info.value.code == 1

    def test_successful_clone_returns_cloned_nodes(self):
        """The changed nodes and their descendants are reported as cloned."""
        assert set(self.run_clone(returncode=0)) == {"model.pkg.parent", "model.pkg.child"}


class TestBuildEphemeralMap:
    """Test the ephemeral map that finalize uses for cleanup."""

    def test_maps_target_and_reference_relations(self):
        """Each cloned node records its CI and production relation; ephemeral models are skipped."""
        from dbt_ci.commands.ephemeral.index import build_ephemeral_map

        def node(name, schema, materialized="table"):
            """Build a minimal model node."""
            return {"id": f"model.pkg.{name}", "name": name, "resource_type": "model", "database": "proj",
                    "schema": schema, "materialized": materialized, "config": {}}

        target = {"model": {"model.pkg.a": node("a", "ci_pr_1"), "model.pkg.e": node("e", "ci_pr_1", "ephemeral")}}
        reference = {"model": {"model.pkg.a": node("a", "analytics")}}

        def make_graph(_args, is_reference=False):
            """Return the reference or target graph depending on the flag."""
            graph = MagicMock()
            graph.to_dict.return_value = reference if is_reference else target
            return graph

        with patch("dbt_ci.commands.ephemeral.index.DbtGraph", side_effect=make_graph):
            ephemeral_map = build_ephemeral_map(Namespace(), ["model.pkg.a", "model.pkg.e"])

        assert list(ephemeral_map) == ["model.pkg.a"]
        assert ephemeral_map["model.pkg.a"]["ephemeral_config"]["schema"] == "ci_pr_1"
        assert ephemeral_map["model.pkg.a"]["reference_config"]["schema"] == "analytics"
