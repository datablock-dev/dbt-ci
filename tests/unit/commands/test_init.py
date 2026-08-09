"""Unit tests for the init command."""
import pytest
from unittest.mock import MagicMock, patch, call
from argparse import Namespace
from dbt_ci.commands.init.index import (
    init as index,
    detect_deleted_models_with_downstream_dependencies,
)
from dbt_ci.graph.parser import generate_dependency_graph


class TestInitCommand:
    """Test the init command."""
    
    @patch('dbt_ci.commands.init.index.CacheManager')
    @patch('dbt_ci.commands.init.index.init_storage_connector')
    @patch('dbt_ci.commands.init.index.DbtCommands')
    @patch('dbt_ci.commands.init.index.StateModified')
    @patch('dbt_ci.commands.init.index.DbtGraph')
    @patch('dbt_ci.commands.init.index.get_manifest_file')
    @patch('dbt_ci.commands.init.index.click.secho')
    def test_init_success_no_modified_nodes(
        self,
        mock_secho,
        mock_get_manifest,
        mock_graph,
        mock_dbt_state,
        mock_dbt_commands,
        mock_storage,
        mock_cache
    ):
        """Test successful init with no modified nodes."""
        # Setup mocks
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance
        mock_storage.return_value = None
        
        # Simulate StateModified.get_state_modified finding no modified nodes and exiting
        mock_dbt_state.return_value.get_state_modified.side_effect = SystemExit(0)
        
        # Mock DbtGraph
        mock_graph_instance = MagicMock()
        mock_graph_instance.to_dict.return_value = {}
        mock_graph.return_value = mock_graph_instance
        
        # Mock manifest file
        mock_get_manifest.return_value = {'metadata': {}}
        
        # Run init - expect SystemExit(0)
        args = Namespace(
            dbt_project_dir='/dbt',
            reference_state='/dbt/.dbtstate',
            reference_vars=None,
            dry_run=False
        )
        with pytest.raises(SystemExit) as exc_info:
            index(args)
        
        # Verify reference compile was called before state check
        mock_dbt_commands.return_value.reference_compile.assert_called_once()
        
        # Verify exit code
        assert exc_info.value.code == 0
    
    @patch('dbt_ci.commands.init.index.CacheManager')
    @patch('dbt_ci.commands.init.index.init_storage_connector')
    @patch('dbt_ci.commands.init.index.DbtCommands')
    @patch('dbt_ci.commands.init.index.StateModified')
    @patch('dbt_ci.commands.init.index.DbtGraph')
    @patch('dbt_ci.commands.init.index.get_manifest_file')
    @patch('dbt_ci.commands.init.index.click.secho')
    @patch('dbt_ci.commands.init.index.init_summary')
    def test_init_success_with_modified_nodes(
        self,
        mock_init_summary,
        mock_secho,
        mock_get_manifest,
        mock_graph,
        mock_dbt_state,
        mock_dbt_commands,
        mock_storage,
        mock_cache
    ):
        """Test successful init with modified nodes."""
        # Setup mocks
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance
        mock_storage.return_value = None
        
        # Mock StateModified.get_state_modified to return a StateChangeSummary
        mock_dbt_state.return_value.get_state_modified.return_value = {
            "modified_nodes": {"model": {"model.project.model1": {"name": "model1", "resource_type": "model"}}},
            "deleted_nodes": {},
            "new_nodes": {}
        }
        
        # Mock graph structure
        mock_graph_instance = MagicMock()
        mock_graph_instance.to_dict.return_value = {
            "model": {
                "model.project.model1": {"name": "model1", "resource_type": "model"}
            }
        }
        mock_graph.return_value = mock_graph_instance
        
        mock_get_manifest.return_value = {"metadata": {}}
        
        # Run init - should complete successfully without raising SystemExit
        args = Namespace(
            dbt_project_dir='/dbt',
            reference_state='/dbt/.dbtstate',
            reference_target='prod',
            reference_vars=None,
            skip_target_compile=False,
            dry_run=False
        )
        index(args)
        
        # Verify cache was written
        assert mock_cache_instance.write_cache.call_count >= 1
        
        # Verify dbt_command_reference_compile was called
        mock_dbt_commands.return_value.reference_compile.assert_called_once()
        
        # Verify state modified was called
        mock_dbt_state.return_value.get_state_modified.assert_called_once()
    
    @patch('dbt_ci.commands.init.index.CacheManager')
    @patch('dbt_ci.commands.init.index.click.secho')
    def test_init_error_handling(
        self,
        mock_secho,
        mock_cache
    ):
        """Test init error handling."""
        # Setup mocks to raise an exception during initialization
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cache.side_effect = Exception("Configuration error")
        mock_cache.return_value = mock_cache_instance
        
        # Run init - expect SystemExit(1)
        args = Namespace(
            dbt_project_dir='/dbt',
            reference_vars=None,
            skip_target_compile=False,
            dry_run=False
        )
        with pytest.raises(SystemExit) as exc_info:
            index(args)
        
        # Verify exit was called with error code
        assert exc_info.value.code == 1
    
    @patch('dbt_ci.commands.init.index.CacheManager')
    @patch('dbt_ci.commands.init.index.init_storage_connector')
    @patch('dbt_ci.commands.init.index.DbtCommands')
    @patch('dbt_ci.commands.init.index.StateModified')
    @patch('dbt_ci.commands.init.index.DbtGraph')
    @patch('dbt_ci.commands.init.index.get_manifest_file')
    @patch('dbt_ci.commands.init.index.click.secho')
    def test_init_with_reference_target(
        self,
        mock_secho,
        mock_get_manifest,
        mock_graph,
        mock_dbt_state,
        mock_dbt_commands,
        mock_storage,
        mock_cache
    ):
        """Test init with reference target specified."""
        # Setup mocks
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance
        mock_storage.return_value = None
        
        # Simulate StateModified.get_state_modified finding no modified nodes and exiting
        mock_dbt_state.return_value.get_state_modified.side_effect = SystemExit(0)
        
        # Mock DbtGraph
        mock_graph_instance = MagicMock()
        mock_graph_instance.to_dict.return_value = {}
        mock_graph.return_value = mock_graph_instance
        
        # Mock manifest file
        mock_get_manifest.return_value = {'metadata': {}}
        
        # Run init - expect SystemExit(0)
        args = Namespace(
            dbt_project_dir='/dbt',
            reference_state='/dbt/.dbtstate',
            reference_target='prod',
            reference_vars=None,
            skip_target_compile=False,
            dry_run=False
        )
        with pytest.raises(SystemExit) as exc_info:
            index(args)
        
        # Verify reference compile was called with reference target internally
        mock_dbt_commands.return_value.reference_compile.assert_called_once()
        
        # Verify exit code
        assert exc_info.value.code == 0


class TestDetectDeletedModelsWithDownstreamDependencies:
    """Test detection and attribution of nodes depending on deleted nodes."""

    def _build_reference_graph(self):
        """
        Build a reference dependency graph with the lineage:
            source_a -> model_x -> model_y
            source_a -> test_t
            source_b -> model_z
        """
        manifest = {
            "metadata": {},
            "nodes": {
                "model.p.model_x": {"name": "model_x", "resource_type": "model", "config": {}, "depends_on": {"macros": [], "nodes": ["source.p.src.source_a"]}},
                "model.p.model_y": {"name": "model_y", "resource_type": "model", "config": {}, "depends_on": {"macros": [], "nodes": ["model.p.model_x"]}},
                "model.p.model_z": {"name": "model_z", "resource_type": "model", "config": {}, "depends_on": {"macros": [], "nodes": ["source.p.src.source_b"]}},
                "test.p.test_t": {"name": "test_t", "resource_type": "test", "config": {}, "depends_on": {"macros": [], "nodes": ["source.p.src.source_a"]}},
            },
            "sources": {
                "source.p.src.source_a": {"name": "source_a", "resource_type": "source", "config": {}},
                "source.p.src.source_b": {"name": "source_b", "resource_type": "source", "config": {}},
            },
            "macros": {},
            "parent_map": {
                "model.p.model_x": ["source.p.src.source_a"],
                "model.p.model_y": ["model.p.model_x"],
                "model.p.model_z": ["source.p.src.source_b"],
                "test.p.test_t": ["source.p.src.source_a"],
                "source.p.src.source_a": [],
                "source.p.src.source_b": [],
            },
            "child_map": {
                "source.p.src.source_a": ["model.p.model_x", "test.p.test_t"],
                "source.p.src.source_b": ["model.p.model_z"],
                "model.p.model_x": ["model.p.model_y"],
                "model.p.model_y": [],
                "model.p.model_z": [],
                "test.p.test_t": [],
            },
        }
        return generate_dependency_graph(manifest)

    def _summary_with_deleted(self, ref_graph, deleted_source_names):
        """Build a StateChangeSummary marking the given source names as deleted."""
        return {
            "modified_nodes": {},
            "new_nodes": {},
            "deleted_nodes": {
                "source": {
                    f"source.p.src.{name}": ref_graph["source"][f"source.p.src.{name}"]
                    for name in deleted_source_names
                }
            },
        }

    @patch("dbt_ci.commands.init.index.click.secho")
    @patch("dbt_ci.commands.init.index.logger")
    @patch("dbt_ci.commands.init.index.DbtGraph")
    def test_attributes_each_dependent_to_its_deleted_node(self, mock_graph, mock_logger, mock_secho):
        """Each surviving dependent is reported against the specific deleted node it relies on."""
        ref_graph = self._build_reference_graph()
        mock_graph.return_value.to_dict.return_value = ref_graph

        summary = self._summary_with_deleted(ref_graph, ["source_a", "source_b"])

        # Advisory only: reports the finding but must not raise / exit.
        detect_deleted_models_with_downstream_dependencies(summary, Namespace())

        logged = "\n".join(str(c.args[0]) for c in mock_logger.error.call_args_list)

        # Direct and transitive dependents of source_a are attributed to source_a
        assert "model_x (model) depends on deleted node(s): source_a" in logged
        assert "model_y (model) depends on deleted node(s): source_a" in logged
        assert "test_t (test) depends on deleted node(s): source_a" in logged
        # model_z is attributed to source_b, not source_a
        assert "model_z (model) depends on deleted node(s): source_b" in logged

    @patch("dbt_ci.commands.init.index.click.secho")
    @patch("dbt_ci.commands.init.index.logger")
    @patch("dbt_ci.commands.init.index.DbtGraph")
    def test_combines_multiple_deleted_nodes_for_one_dependent(self, mock_graph, mock_logger, mock_secho):
        """A dependent that relies on several deleted nodes lists all of them, sorted."""
        ref_graph = self._build_reference_graph()
        # model_y transitively depends on both source_a (via model_x) and model_x itself.
        mock_graph.return_value.to_dict.return_value = ref_graph

        summary = self._summary_with_deleted(ref_graph, ["source_a"])
        # Also mark model_x as deleted so model_y depends on two deleted nodes.
        summary["deleted_nodes"]["model"] = {
            "model.p.model_x": ref_graph["model"]["model.p.model_x"]
        }

        detect_deleted_models_with_downstream_dependencies(summary, Namespace())

        logged = "\n".join(str(c.args[0]) for c in mock_logger.error.call_args_list)
        # model_y depends on both deleted nodes; deleted nodes are themselves excluded from the report.
        assert "model_y (model) depends on deleted node(s): model_x, source_a" in logged
        assert "model_x (model) depends on" not in logged  # model_x is deleted, not reported

    @patch("dbt_ci.commands.init.index.DbtGraph")
    def test_no_deleted_nodes_is_a_noop(self, mock_graph):
        """No deleted nodes means no graph is built and no exit occurs."""
        summary = {"modified_nodes": {}, "new_nodes": {}, "deleted_nodes": {}}
        detect_deleted_models_with_downstream_dependencies(summary, Namespace())
        mock_graph.assert_not_called()

    @patch("dbt_ci.commands.init.index.DbtGraph")
    def test_deleted_node_with_no_surviving_dependents_does_not_exit(self, mock_graph):
        """A deleted leaf node with no downstream dependents should not raise SystemExit."""
        ref_graph = self._build_reference_graph()
        mock_graph.return_value.to_dict.return_value = ref_graph

        # model_y is a leaf — nothing depends on it, so deleting it is safe.
        summary = {
            "modified_nodes": {},
            "new_nodes": {},
            "deleted_nodes": {"model": {"model.p.model_y": ref_graph["model"]["model.p.model_y"]}},
        }
        detect_deleted_models_with_downstream_dependencies(summary, Namespace())  # no SystemExit


class TestResolveManifestFromStorage:
    """Test the resolve_manifest_file_from_storage helper function."""
    
    @patch('builtins.open', new_callable=MagicMock)
    @patch('dbt_ci.commands.init.resolve_manifest.Path')
    @patch('dbt_ci.commands.init.resolve_manifest.logger')
    def test_resolve_manifest_creates_directory(self, mock_logger, mock_path, mock_open):
        """Test that the function creates the necessary directory."""
        from dbt_ci.commands.init.resolve_manifest import resolve_manifest_file_from_storage
        
        # Setup mocks
        storage_connector = {
            "download": MagicMock(return_value={"metadata": {}})
        }
        state_uri = "s3://bucket/path"
        variables = Namespace(
            reference_state='dbt/.dbtstate',
            dbt_project_dir='dbt',
            state='dbt/.dbtstate',
            runner='local'
        )
        
        # Mock Path operations
        mock_path_instance = MagicMock()
        mock_path.return_value = mock_path_instance
        mock_path.cwd.return_value = mock_path_instance
        
        # Run function
        resolve_manifest_file_from_storage((storage_connector, state_uri), variables)
        
        # Verify download was called
        storage_connector["download"].assert_called_once_with(state_uri)
