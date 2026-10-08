"""Unit tests for the run command."""
import pytest
from unittest.mock import MagicMock, patch, call
from argparse import Namespace
from dbt_ci.commands.run.index import run as index
from dbt_ci.commands.run.run import run_nodes


class TestRunCommand:
    """Test the run command."""
    
    @patch('dbt_ci.commands.run.index.CacheManager')
    @patch('dbt_ci.commands.run.index.DbtGraph')
    @patch('dbt_ci.commands.run.index.print_exception')
    @patch('dbt_ci.commands.run.index.click.secho')
    def test_run_no_cache(
        self,
        mock_secho,
        mock_print_exception,
        mock_graph,
        mock_cache
    ):
        """Test run command fails when no cache is found, since init never ran."""
        # Setup mocks
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.return_value = None
        mock_cache.return_value = mock_cache_instance
        # Run command
        args = Namespace(
            dbt_project_dir='/dbt',
            dry_run=False
        )
        with pytest.raises(SystemExit) as exc_info:
            index(args)

        assert exc_info.value.code == 1
        assert "No cache found" in str(mock_print_exception.call_args[0][0])
        mock_cache_instance.update_report.assert_called_with("run", "failed", comment=str(mock_print_exception.call_args[0][0]))
    
    @patch('dbt_ci.commands.run.index.CacheManager')
    @patch('dbt_ci.commands.run.index.DbtGraph')
    @patch('dbt_ci.commands.run.index.get_node_ids_from_structured_nodes')
    @patch('dbt_ci.commands.run.index.run_nodes')
    @patch('dbt_ci.commands.run.index.logger.info')
    @patch('dbt_ci.commands.run.index.click.secho')
    def test_run_no_modified_nodes(
        self,
        mock_secho,
        mock_logger_info,
        mock_run_nodes,
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
    @patch('dbt_ci.commands.run.index.run_nodes')
    @patch('dbt_ci.commands.run.index.click.secho')
    @patch('dbt_ci.commands.run.index.click.echo')
    def test_run_with_modified_nodes(
        self,
        mock_echo,
        mock_secho,
        mock_run_nodes,
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
        
        # Verify run_nodes was called
        mock_run_nodes.assert_called_once()
    
    @patch('dbt_ci.commands.run.index.CacheManager')
    @patch('dbt_ci.commands.run.index.click.echo')
    @patch('dbt_ci.commands.run.index.sys.exit')
    def test_run_error_handling(
        self,
        mock_exit,
        mock_echo,
        mock_cache
    ):
        """Test run command error handling."""
        # First CacheManager call (in try block) raises, second (in except block) returns mock
        mock_cache.side_effect = [Exception("Cache error"), MagicMock()]
        args = Namespace(
            dbt_project_dir='/dbt',
            dry_run=False
        )
        index(args)
        
        # Verify error was handled
        mock_exit.assert_called_once_with(1)


def _graph_node(unique_id: str, fqn: list[str] | None = None) -> dict:
    """Build the minimal graph entry get_selectors and display_name need."""
    name = unique_id.split(".")[-1]
    return {
        "id": unique_id,
        "name": name,
        "fqn": fqn if fqn is not None else unique_id.split(".")[1:],
        "resource_type": unique_id.split(".")[0],
    }


def _graph(*unique_ids: str) -> dict:
    """Build a dependency graph keyed by unique_id, bucketed by resource type."""
    graph: dict = {"model": {}, "seed": {}, "snapshot": {}, "test": {}}
    for unique_id in unique_ids:
        graph.setdefault(unique_id.split(".")[0], {})[unique_id] = _graph_node(unique_id)
    return graph


class TestRunNodes:
    """Test the run_nodes helper function."""

    @patch('dbt_ci.commands.run.run.run_dbt_command')
    @patch('dbt_ci.commands.run.run.get_downstream_dependencies')
    @patch('dbt_ci.commands.run.run.get_upstream_dependencies')
    @patch('dbt_ci.commands.run.run.filter_node_ids_by_type')
    def test_run_nodes_all(
        self,
        mock_filter,
        mock_upstream,
        mock_downstream,
        mock_run_cmd
    ):
        """Test run_nodes with 'all' mode runs all command types."""
        variables = Namespace(dry_run=False, nodes='all', runner='local')
        target_graph = MagicMock()
        target_graph.to_dict.return_value = _graph(
            "model.project.model1", "model.project.model2"
        )
        modified_nodes_dict = {
            "modified_nodes": ["model.project.model1"],
            "new_nodes": ["model.project.model2"],
            "deleted_nodes": []
        }
        modified_nodes = ["model.project.model1", "model.project.model2"]

        mock_upstream.return_value = []
        mock_downstream.return_value = []
        mock_filter.return_value = ["model.project.model1", "model.project.model2"]

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run_cmd.return_value = mock_result

        run_nodes(args=variables, target_graph=target_graph, changed_nodes=modified_nodes, changed_nodes_dict=modified_nodes_dict)

        # Should have attempted to run nodes
        assert mock_run_cmd.call_count >= 1

    @patch('dbt_ci.commands.run.run.run_dbt_command')
    @patch('dbt_ci.commands.run.run.get_downstream_dependencies')
    @patch('dbt_ci.commands.run.run.filter_node_ids_by_type')
    def test_run_nodes_models_only(
        self,
        mock_filter,
        mock_downstream,
        mock_run_cmd
    ):
        """Test run_nodes with 'models' mode only runs models."""
        variables = Namespace(dry_run=False, nodes='models', runner='local')
        target_graph = MagicMock()
        target_graph.to_dict.return_value = _graph(
            "model.project.model1", "model.project.model3"
        )
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

        run_nodes(args=variables, target_graph=target_graph, changed_nodes=modified_nodes, changed_nodes_dict=modified_nodes_dict)

        mock_run_cmd.assert_called_once()

    @patch('dbt_ci.commands.run.run.get_downstream_dependencies')
    @patch('dbt_ci.commands.run.run.filter_node_ids_by_type')
    @patch('dbt_ci.commands.run.run.logger.info')
    def test_run_nodes_no_nodes(
        self,
        mock_logger_info,
        mock_filter,
        mock_downstream
    ):
        """Test run_nodes skips gracefully when no nodes match."""
        variables = Namespace(dry_run=False, nodes='models')
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

        run_nodes(args=variables, target_graph=target_graph, changed_nodes=modified_nodes, changed_nodes_dict=modified_nodes_dict)

        mock_logger_info.assert_any_call("No nodes to run for run, skipping...")

    @patch('dbt_ci.commands.run.run.run_dbt_command')
    @patch('dbt_ci.commands.run.run.get_downstream_dependencies')
    @patch('dbt_ci.commands.run.run.filter_node_ids_by_type')
    @patch('dbt_ci.commands.run.run.logger.info')
    def test_run_nodes_dry_run(
        self,
        mock_logger_info,
        mock_filter,
        mock_downstream,
        mock_run_cmd
    ):
        """Test run_nodes skips dbt execution in dry run mode."""
        variables = Namespace(dry_run=True, nodes='models')
        target_graph = MagicMock()
        target_graph.to_dict.return_value = _graph("model.project.model1")
        modified_nodes_dict = {
            "modified_nodes": ["model.project.model1"],
            "new_nodes": [],
            "deleted_nodes": []
        }
        modified_nodes = ["model.project.model1"]

        mock_downstream.return_value = []
        mock_filter.return_value = ["model.project.model1"]

        run_nodes(args=variables, target_graph=target_graph, changed_nodes=modified_nodes, changed_nodes_dict=modified_nodes_dict)

        mock_run_cmd.assert_not_called()
        mock_logger_info.assert_any_call("DRY RUN: Command would be executed")


# ---------------------------------------------------------------------------
# Run order and test selection against a small parsed manifest
# ---------------------------------------------------------------------------

from dbt_ci.graph.parser import generate_dependency_graph
from dbt_ci.commands.run.run import tests as select_tests


def _manifest_graph() -> dict:
    """Parse a manifest with a -> b, a data test on each model and a unit test on b."""
    def model(name, parents=()):
        """Build a model entry."""
        return {"name": name, "resource_type": "model", "fqn": ["demo", name], "database": "db",
                "schema": "sc", "original_file_path": f"models/{name}.sql", "config": {},
                "columns": {}, "depends_on": {"macros": [], "nodes": list(parents)}}

    def data_test(name, parent):
        """Build a data test entry."""
        return {"name": name, "resource_type": "test", "fqn": ["demo", name], "original_file_path": "models/schema.yml",
                "config": {}, "columns": {}, "depends_on": {"macros": [], "nodes": [parent]}}

    nodes = {
        "model.demo.a": model("a"),
        "model.demo.b": model("b", ["model.demo.a"]),
        "test.demo.t_a": data_test("t_a", "model.demo.a"),
        "test.demo.t_b": data_test("t_b", "model.demo.b"),
    }
    unit_tests = {"unit_test.demo.b.ut_b": {
        "name": "ut_b", "resource_type": "unit_test", "fqn": ["demo", "b", "ut_b"],
        "original_file_path": "models/schema.yml", "config": {}, "depends_on": {"macros": [], "nodes": ["model.demo.b"]},
    }}
    entries = {**nodes, **unit_tests}
    parent_map = {node_id: node["depends_on"]["nodes"] for node_id, node in entries.items()}
    child_map = {node_id: [c for c, ps in parent_map.items() if node_id in ps] for node_id in entries}
    return generate_dependency_graph({"metadata": {}, "nodes": nodes, "unit_tests": unit_tests, "macros": {},
                                      "sources": {}, "parent_map": parent_map, "child_map": child_map})


class TestRunOrder:
    """Test the order in which run_nodes executes dbt commands in --mode all."""

    def test_snapshots_run_before_models_and_tests_last(self):
        """Models built on a changed snapshot must see its new state."""
        executed = []
        stub = lambda name: (lambda **_kwargs: [f"{name}.demo.x"])
        with patch.dict("dbt_ci.commands.run.run.__dict__", {
            "seeds": stub("seed"), "snapshots": stub("snapshot"), "models": stub("model"), "tests": stub("test"),
        }), patch("dbt_ci.commands.run.run.get_selectors", return_value=["demo.x"]), \
             patch("dbt_ci.commands.run.run.resolve_dbt_commands", side_effect=lambda cmd, _args: cmd), \
             patch("dbt_ci.commands.run.run.run_dbt_command",
                   side_effect=lambda command_args, runner_config: executed.append(command_args[0]) or MagicMock(returncode=0)), \
             patch("dbt_ci.commands.run.run.log_nodes_to_run"):
            run_nodes(Namespace(nodes="all", dry_run=False), MagicMock(), ["model.demo.x"], {"modified_nodes": ["model.demo.x"]})
        assert executed == ["seed", "snapshot", "run", "test"]


class TestTestSelection:
    """Test which data and unit tests the test step selects."""

    def select(self, depth=None):
        """Select tests for a change to model a."""
        graph = MagicMock()
        graph.to_dict.return_value = _manifest_graph()
        return set(select_tests(graph, {"modified_nodes": ["model.demo.a"]}, ["model.demo.a"],
                                Namespace(downstream_depth=depth, filters=None)))

    def test_full_graph_includes_unit_tests(self):
        """Unit tests downstream of a change run alongside data tests."""
        assert self.select() == {"test.demo.t_a", "test.demo.t_b", "unit_test.demo.b.ut_b"}

    def test_depth_zero_keeps_tests_of_the_changed_model(self):
        """Depth 0 builds only a, but a's own tests must still run."""
        assert self.select(depth=0) == {"test.demo.t_a"}

    def test_depth_one_keeps_tests_of_the_deepest_built_model(self):
        """Depth 1 builds b, so b's data and unit tests (one level further down) run too."""
        assert self.select(depth=1) == {"test.demo.t_a", "test.demo.t_b", "unit_test.demo.b.ut_b"}
