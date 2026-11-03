"""Unit tests for run --skip-test-only-changes."""

from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest

from dbt_ci.commands.run.index import skip_test_only_nodes
from dbt_ci.commands.run.run import models as select_models
from dbt_ci.commands.run.run import tests as select_tests
from dbt_ci.commands.run.skip_test_only import find_test_only_changes, without_tests
from dbt_ci.graph.parser import generate_dependency_graph

GIT = "dbt_ci.commands.run.skip_test_only.GitAdapter"

BASE_YAML = """
version: 2
models:
  - name: a
    description: Model a
    columns:
      - name: id
        data_tests:
          - unique
  - name: b
    description: Model b
seeds:
  - name: s
    description: Seed s
"""

# Only tests differ from BASE_YAML: a new column-level and model-level test on a
TEST_ONLY_YAML = """
version: 2
models:
  - name: a
    description: Model a
    data_tests:
      - dbt_utils.expression_is_true:
          expression: "id > 0"
    columns:
      - name: id
        data_tests:
          - unique
          - not_null
  - name: b
    description: Model b
seeds:
  - name: s
    description: Seed s
"""


def _manifest_graph() -> dict:
    """Parse a manifest with a -> b, a seed, a macro used by b and a test on a and b."""

    def node(name, resource_type, path, parents=(), macros=(), patch_path="models/schema.yml"):
        """Build a manifest node entry."""
        return {
            "name": name,
            "resource_type": resource_type,
            "fqn": ["demo", name],
            "database": "db",
            "schema": "sc",
            "original_file_path": path,
            "patch_path": f"demo://{patch_path}" if patch_path else None,
            "config": {},
            "columns": {},
            "depends_on": {"macros": list(macros), "nodes": list(parents)},
        }

    nodes = {
        "model.demo.a": node("a", "model", "models/a.sql"),
        "model.demo.b": node("b", "model", "models/b.sql", ["model.demo.a"], ["macro.demo.helper"]),
        "seed.demo.s": node("s", "seed", "seeds/s.csv"),
        "test.demo.not_null_a_id": node(
            "not_null_a_id", "test", "models/schema.yml", ["model.demo.a"], patch_path=None
        ),
        "test.demo.t_b": node(
            "t_b", "test", "models/schema.yml", ["model.demo.b"], patch_path=None
        ),
    }
    macros = {
        "macro.demo.helper": {
            "name": "helper",
            "original_file_path": "macros/helper.sql",
            "depends_on": {"macros": []},
        }
    }
    parent_map = {node_id: entry["depends_on"]["nodes"] for node_id, entry in nodes.items()}
    child_map = {node_id: [c for c, ps in parent_map.items() if node_id in ps] for node_id in nodes}
    return generate_dependency_graph(
        {
            "metadata": {},
            "nodes": nodes,
            "macros": macros,
            "sources": {},
            "parent_map": parent_map,
            "child_map": child_map,
        }
    )


@pytest.fixture
def project(tmp_path):
    """A dbt project directory whose models/schema.yml holds only test changes."""
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "schema.yml").write_text(TEST_ONLY_YAML, encoding="utf-8")
    return tmp_path


def _find(project, changed, base_yaml=BASE_YAML, node_ids=("model.demo.a",)):
    """Run find_test_only_changes with git returning the given diff and base YAML."""
    git = MagicMock()
    git.get_changed_files.return_value = {"modified": list(changed)}
    git.read_base_file.return_value = base_yaml
    with patch(GIT, return_value=git):
        return find_test_only_changes(
            Namespace(dbt_project_dir=str(project)), _manifest_graph(), list(node_ids)
        )


class TestFindTestOnlyChanges:
    """Test which modified nodes count as changed only in their tests."""

    def test_new_tests_only(self, project):
        """Added model- and column-level tests leave the model out of the build."""
        assert _find(project, ["models/schema.yml"]) == {"model.demo.a"}

    def test_unchanged_neighbours_in_the_same_file(self, project):
        """The git strategy marks every model in the file; untouched ones are skipped too."""
        node_ids = ("model.demo.a", "model.demo.b", "seed.demo.s")
        assert _find(project, ["models/schema.yml"], node_ids=node_ids) == {
            "model.demo.a",
            "model.demo.b",
            "seed.demo.s",
        }

    def test_property_change_is_built(self, project):
        """A change outside the tests, here a description, is a real change."""
        base = BASE_YAML.replace("description: Model a", "description: Old description")
        assert _find(project, ["models/schema.yml"], base_yaml=base) == set()

    def test_sql_change_is_built(self, project):
        """A model whose own file changed is built whatever happened to its tests."""
        assert _find(project, ["models/schema.yml", "models/a.sql"]) == set()

    def test_macro_change_is_built(self, project):
        """A model calling a changed macro is built."""
        changed = ["models/schema.yml", "macros/helper.sql"]
        assert _find(project, changed, node_ids=("model.demo.b",)) == set()

    @pytest.mark.parametrize("project_file", ["dbt_project.yml", "packages.yml"])
    def test_project_file_change_builds_everything(self, project, project_file):
        """Project-level files can change any node's config, so nothing is skipped."""
        assert _find(project, ["models/schema.yml", project_file]) == set()

    def test_properties_file_unchanged_is_built(self, project):
        """Without a YAML change, nothing in the diff says the change was to tests."""
        assert _find(project, ["models/other.yml"]) == set()

    def test_entry_missing_at_base_is_built(self, project):
        """Properties moved in from another file can't be compared, so the model is built."""
        assert _find(project, ["models/schema.yml"], base_yaml=None) == set()

    def test_tests_are_never_candidates(self, project):
        """Only buildable nodes are returned; changed tests stay in the change set."""
        assert _find(project, ["models/schema.yml"], node_ids=("test.demo.not_null_a_id",)) == set()

    def test_git_failure_builds_everything(self, project):
        """A failing git diff disables the option rather than failing the run."""
        with patch(GIT, side_effect=RuntimeError("no base branch")):
            result = find_test_only_changes(
                Namespace(dbt_project_dir=str(project)), _manifest_graph(), ["model.demo.a"]
            )
        assert result == set()


class TestWithoutTests:
    """Test that tests are stripped at every level they can be declared."""

    def test_strips_resource_column_and_version_tests(self):
        """tests and data_tests go; everything else is kept."""
        entry = {
            "name": "a",
            "tests": ["x"],
            "data_tests": ["y"],
            "columns": [{"name": "id", "tests": ["unique"], "description": "Id"}],
            "versions": [{"v": 1, "columns": [{"name": "id", "data_tests": ["not_null"]}]}],
        }
        assert without_tests(entry) == {
            "name": "a",
            "columns": [{"name": "id", "description": "Id"}],
            "versions": [{"v": 1, "columns": [{"name": "id"}]}],
        }


class TestSkipTestOnlyNodes:
    """Test the effect of the option on what run selects."""

    def test_model_is_skipped_but_its_changed_test_runs(self):
        """The changed test runs; neither the model nor its downstream model is rebuilt."""
        graph = MagicMock()
        graph.to_dict.return_value = _manifest_graph()
        changed = {
            "modified_nodes": ["model.demo.a"],
            "new_nodes": ["test.demo.not_null_a_id"],
            "deleted_nodes": [],
        }
        args = Namespace(downstream_depth=None, filters=None, defer=True)

        with patch(
            "dbt_ci.commands.run.index.find_test_only_changes", return_value={"model.demo.a"}
        ):
            skip_test_only_nodes(args, graph, changed)

        changed_nodes = changed["modified_nodes"] + changed["new_nodes"]
        assert changed["modified_nodes"] == []
        assert select_models(graph, changed, changed_nodes, args) == []
        assert select_tests(graph, changed, changed_nodes, args) == ["test.demo.not_null_a_id"]

    def test_warns_without_defer(self, caplog):
        """Without --defer the tests of a skipped model may have no table to query."""
        graph = MagicMock()
        graph.to_dict.return_value = _manifest_graph()
        changed = {"modified_nodes": ["model.demo.a"], "new_nodes": [], "deleted_nodes": []}

        with patch(
            "dbt_ci.commands.run.index.find_test_only_changes", return_value={"model.demo.a"}
        ):
            skip_test_only_nodes(Namespace(defer=False), graph, changed)

        assert "Without --defer" in caplog.text
