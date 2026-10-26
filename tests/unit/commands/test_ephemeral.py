"""Unit tests for the ephemeral command."""
import logging
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


def _graph_node(unique_id, upstream_by_type=None, downstream_by_type=None):
    """Build a graph node carrying only what clone_command reads."""
    resource_type, package, name = unique_id.split(".")
    return {"id": unique_id, "name": name, "resource_type": resource_type, "fqn": [package, name],
            "upstream_dependencies": {"dependencies_by_type": upstream_by_type or {}},
            "indirect_downstream_dependencies": {"dependencies_by_type": downstream_by_type or {}}}


SEED_TESTS = ["test.pkg.not_null_items_id", "test.pkg.unique_items_id"]


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

    def run_clone_on_graph(self, graph, modified_nodes, new_nodes):
        """Invoke clone_command against a real graph, keeping the mocked dbt calls on self."""
        from dbt_ci.commands.ephemeral.clone import clone_command

        target_graph = MagicMock()
        target_graph.to_dict.return_value = graph
        self.mock_resolve = MagicMock(side_effect=lambda command_args, args: command_args)
        self.mock_run = MagicMock(return_value=MagicMock(returncode=0))
        with patch("dbt_ci.commands.ephemeral.clone.get_profile", return_value={"threads": 1}), \
             patch("dbt_ci.commands.ephemeral.clone.DbtGraph", return_value=target_graph), \
             patch("dbt_ci.commands.ephemeral.clone.resolve_dbt_commands", self.mock_resolve), \
             patch("dbt_ci.commands.ephemeral.clone.run_dbt_command", self.mock_run):
            return clone_command(
                {"modified_nodes": modified_nodes, "new_nodes": new_nodes, "deleted_nodes": []},
                Namespace(dry_run=False),
            )

    def test_changed_leaf_model_clones_its_parents(self):
        """A changed model with no descendants still gets its direct model parents cloned, but not its seeds."""
        graph = {
            "model": {
                "model.pkg.mrt_leaf": _graph_node("model.pkg.mrt_leaf", {
                    "model": ["model.pkg.itr_a", "model.pkg.itr_b"],
                    "seed": ["seed.pkg.lookup"],
                }),
                "model.pkg.itr_a": _graph_node("model.pkg.itr_a", {"model": ["model.pkg.stg_a"]}),
                "model.pkg.itr_b": _graph_node("model.pkg.itr_b"),
                "model.pkg.stg_a": _graph_node("model.pkg.stg_a"),
            },
            "seed": {"seed.pkg.lookup": _graph_node("seed.pkg.lookup")},
        }

        cloned_nodes = self.run_clone_on_graph(graph, ["model.pkg.mrt_leaf"], [])

        command = self.mock_resolve.call_args.kwargs["command_args"]
        assert command == ["clone", "--select", "1+pkg.mrt_leaf+", "--exclude", "pkg.lookup", "--threads", "1"]
        assert set(cloned_nodes) == {"model.pkg.mrt_leaf", "model.pkg.itr_a", "model.pkg.itr_b"}

    def test_changed_snapshot_without_descendants_is_cloned(self):
        """A changed snapshot with nothing downstream is still cloned, together with the model it reads."""
        graph = {
            "model": {"model.pkg.src": _graph_node("model.pkg.src")},
            "snapshot": {"snapshot.pkg.snap": _graph_node("snapshot.pkg.snap", {"model": ["model.pkg.src"]})},
        }

        cloned_nodes = self.run_clone_on_graph(graph, ["snapshot.pkg.snap"], [])

        command = self.mock_resolve.call_args.kwargs["command_args"]
        assert command[:2] == ["clone", "--select"] and command[-2:] == ["--threads", "1"]
        assert set(command[2:-2]) == {"1+pkg.snap+", "1+pkg.src"}
        self.mock_run.assert_called_once()
        assert set(cloned_nodes) == {"snapshot.pkg.snap", "model.pkg.src"}

    @pytest.mark.parametrize("modified_nodes, new_nodes", [
        pytest.param([], ["seed.pkg.items", *SEED_TESTS], id="new-seed-and-its-tests"),
        pytest.param(["seed.pkg.items"], [], id="modified-seed"),
        pytest.param(SEED_TESTS[:1], [], id="modified-test-on-a-seed"),
        pytest.param([], [], id="no-changes"),
    ])
    def test_change_without_models_or_snapshots_skips_clone(self, caplog, modified_nodes, new_nodes):
        """A change that selects no model or snapshot leaves nothing to clone, so no dbt clone runs."""
        graph = {
            "seed": {"seed.pkg.items": _graph_node("seed.pkg.items", downstream_by_type={"test": SEED_TESTS})},
            "test": {test_id: _graph_node(test_id, {"seed": ["seed.pkg.items"]}) for test_id in SEED_TESTS},
        }

        with caplog.at_level(logging.INFO), pytest.raises(SystemExit) as exc_info:
            self.run_clone_on_graph(graph, modified_nodes, new_nodes)

        assert exc_info.value.code == 0
        self.mock_resolve.assert_not_called()
        self.mock_run.assert_not_called()
        assert "No models or snapshots to clone" in caplog.text


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

    def test_prefers_the_manifest_dbt_clone_wrote(self):
        """The clone's own manifest (compiled for the CI target) decides where the clones are."""
        from dbt_ci.commands.ephemeral.index import build_ephemeral_map

        def node(name, schema):
            """Build a minimal model node."""
            return {"id": f"model.pkg.{name}", "name": name, "resource_type": "model", "database": "db",
                    "schema": schema, "materialized": "table", "config": {}}

        cached_target = {"model": {"model.pkg.a": node("a", "analytics")}}
        clone_manifest_graph = {"model": {"model.pkg.a": node("a", "ci_pr_1")}}
        reference = {"model": {"model.pkg.a": node("a", "analytics")}}

        def make_graph(_args, is_reference=False):
            """Return the reference or cached target graph depending on the flag."""
            graph = MagicMock()
            graph.to_dict.return_value = reference if is_reference else cached_target
            return graph

        with patch("dbt_ci.commands.ephemeral.index.DbtGraph", side_effect=make_graph), \
             patch("dbt_ci.commands.ephemeral.index.get_manifest_file", return_value={}), \
             patch("dbt_ci.commands.ephemeral.index.generate_dependency_graph", return_value=clone_manifest_graph):
            ephemeral_map = build_ephemeral_map(Namespace(dbt_project_dir="dbt"), ["model.pkg.a"])

        assert ephemeral_map["model.pkg.a"]["ephemeral_config"]["schema"] == "ci_pr_1"
        assert ephemeral_map["model.pkg.a"]["reference_config"]["schema"] == "analytics"
