"""Tests for dropping relations and schemas through dbt run-operation."""
import json
from argparse import Namespace
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import pytest
import yaml

from dbt_ci.connectors import get_connector
from dbt_ci.dbt import operations
from dbt_ci.dbt.operations import drop_relations, drop_schemas, operation_command, write_operations_project


@pytest.fixture
def project(tmp_path):
    """A dbt project directory with a dbt_project.yml naming its profile."""
    project_dir = tmp_path / "dbt"
    project_dir.mkdir()
    (project_dir / "dbt_project.yml").write_text("name: shop\nprofile: warehouse\n")
    return project_dir


def args_for(project_dir, **overrides) -> Namespace:
    """Build the args a command would pass, with the local runner by default."""
    values = {
        "dbt_project_dir": str(project_dir),
        "profiles_dir": str(project_dir),
        "reference_state": str(project_dir / "state"),
        "target": "ci",
        "vars": "",
        "runner": "local",
        "defer": False,
    }
    values.update(overrides)
    return Namespace(**values)


def test_helper_project_uses_the_users_profile(project):
    """The helper project carries dbt-ci's macros and points at the user's profile."""
    operations_dir = write_operations_project(args_for(project))

    assert operations_dir == project / "target" / "dbt_ci_operations"
    config = yaml.safe_load((operations_dir / "dbt_project.yml").read_text())
    assert config["profile"] == "warehouse"
    assert config["macro-paths"] == ["macros"]
    macros = (operations_dir / "macros" / "dbt_ci_operations.sql").read_text()
    assert "macro dbt_ci_drop_relations" in macros and "macro dbt_ci_drop_schemas" in macros
    assert (operations_dir / ".gitignore").read_text() == "*\n"


def test_command_points_at_the_helper_project_on_the_host(project):
    """Host runners get the absolute helper path, the user's profiles and target, and no state."""
    command = operation_command(args_for(project), "dbt_ci_drop_schemas", {"schemas": []})

    assert command[:4] == ["run-operation", "dbt_ci_drop_schemas", "--args", '{"schemas": []}']
    assert command[command.index("--project-dir") + 1] == str((project / "target" / "dbt_ci_operations").resolve())
    assert command[command.index("--profiles-dir") + 1] == str(project.resolve())
    assert command[command.index("--target") + 1] == "ci"
    assert "--state" not in command and "--no-defer" not in command and "--defer" not in command


def test_command_uses_the_container_path_with_docker(project):
    """With Docker, the helper path is derived from the project's path inside the container."""
    args = args_for(project, runner="docker", docker_volumes=[f"{project}:/workspace/dbt"], docker_env=[])
    command = operation_command(args, "dbt_ci_drop_schemas", {"schemas": []})

    assert command[command.index("--project-dir") + 1] == "/workspace/dbt/target/dbt_ci_operations"


def test_command_fails_when_the_project_is_not_in_the_container(project):
    """Without a volume for the project, the helper project cannot be reached."""
    args = args_for(project, runner="docker", docker_volumes=[], docker_env=[])
    with pytest.raises(RuntimeError, match="Docker container"):
        operation_command(args, "dbt_ci_drop_schemas", {"schemas": []})


def test_drop_relations_runs_the_macro_with_its_arguments(project):
    """drop_relations writes the helper project and runs the macro through the runner."""
    relations = [{"database": "db", "schema": "main", "identifier": "legacy"}]
    with patch.object(operations, "run_dbt_command", return_value=CompletedProcess([], 0)) as run:
        drop_relations(args_for(project), relations)

    command = run.call_args.kwargs["command_args"]
    assert command[1] == "dbt_ci_drop_relations"
    assert json.loads(command[3]) == {"relations": relations}
    assert (project / "target" / "dbt_ci_operations" / "dbt_project.yml").exists()


def test_failed_operation_raises(project):
    """A failing macro fails the command instead of passing silently."""
    with patch.object(operations, "run_dbt_command", return_value=CompletedProcess([], 1)):
        with pytest.raises(RuntimeError, match="dbt_ci_drop_schemas failed"):
            drop_schemas(args_for(project), [{"database": None, "schema": "ci"}])


def test_nothing_to_drop_runs_nothing(project):
    """Empty lists do not start dbt."""
    with patch.object(operations, "run_dbt_command") as run:
        drop_relations(args_for(project), [])
        drop_schemas(args_for(project), [])
    run.assert_not_called()


def test_unknown_adapter_has_no_native_connector():
    """Adapters without a native connector are not an error; they use the dbt path."""
    assert get_connector("snowflake") is None
    assert get_connector("bigquery") is not None


class TestDeleteFallback:
    """delete drops through dbt when the adapter has no native connector."""

    def test_dbt_strategy_drops_each_relation_and_its_tmp_table(self):
        """Every deleted node's relation and dbt's leftover __dbt_tmp relation are dropped."""
        from dbt_ci.commands.delete.index import dbt_delete_strategy

        delete_map = {
            "model.shop.legacy": {
                "type": "model", "name": "legacy", "table_id": "db.main.legacy",
                "database": "db", "schema": "main", "identifier": "legacy",
            }
        }
        with patch("dbt_ci.commands.delete.index.drop_relations") as drop:
            dbt_delete_strategy(delete_map, Namespace())

        assert drop.call_args.args[1] == [
            {"database": "db", "schema": "main", "identifier": "legacy"},
            {"database": "db", "schema": "main", "identifier": "legacy__dbt_tmp"},
        ]

    def test_table_id_without_a_database(self):
        """Adapters without databases (e.g. Spark) are identified by schema and alias."""
        from dbt_ci.commands.delete.index import get_table_id

        assert get_table_id({"database": None, "schema": "main", "name": "a", "config": {}}) == "main.a"
        assert get_table_id({"database": "db", "schema": "main", "name": "a", "config": {}}) == "db.main.a"
        assert get_table_id({"database": "db", "schema": None, "name": "a", "config": {}}) is None


class TestDestroyFallback:
    """ephemeral destroy drops schemas through dbt when the adapter has no native connector."""

    EPHEMERAL_MAP = {
        "model.shop.a": {
            "name": "a", "resource_type": "model",
            "ephemeral_config": {"database": "db", "schema": "ci", "name": "a", "alias": "a"},
            "reference_config": {"database": "db", "schema": "main", "name": "a", "alias": "a"},
        },
        "model.shop.b": {
            "name": "b", "resource_type": "model",
            "ephemeral_config": {"database": "db", "schema": "main", "name": "b", "alias": "b"},
            "reference_config": {"database": "db", "schema": "main", "name": "b", "alias": "b"},
        },
    }

    def run_cleanup(self, dry_run=False):
        """Run the cleanup against a Snowflake profile and return the drop_schemas mock."""
        from dbt_ci.commands.ephemeral.destroy import clean_up_ephemeral

        cache = MagicMock()
        cache.get_cache.side_effect = lambda name: self.EPHEMERAL_MAP if name == "ephemeral_map.json" else {}
        with patch("dbt_ci.commands.ephemeral.destroy.get_profile", return_value={"type": "snowflake"}), \
             patch("dbt_ci.commands.ephemeral.destroy.get_reference_datasets", return_value={"db.main"}), \
             patch("dbt_ci.commands.ephemeral.destroy.drop_schemas") as drop:
            clean_up_ephemeral(Namespace(dry_run=dry_run), cache)
        return drop

    def test_drops_only_the_ci_schema(self):
        """The production schema is refused; the CI schema is dropped through dbt."""
        drop = self.run_cleanup()
        assert drop.call_args.args[1] == [{"database": "db", "schema": "ci"}]

    def test_production_schema_is_protected_whatever_its_case(self):
        """A CI config that resolves to production's schema in another case is still refused."""
        from dbt_ci.commands.ephemeral.destroy import clean_up_ephemeral

        cache = MagicMock()
        cache.get_cache.side_effect = lambda name: self.EPHEMERAL_MAP if name == "ephemeral_map.json" else {}
        with patch("dbt_ci.commands.ephemeral.destroy.get_profile", return_value={"type": "snowflake"}), \
             patch("dbt_ci.commands.ephemeral.destroy.get_reference_datasets", return_value={"DB.CI"}), \
             patch("dbt_ci.commands.ephemeral.destroy.drop_schemas") as drop:
            clean_up_ephemeral(Namespace(dry_run=False), cache)
        drop.assert_not_called()

    def test_dry_run_drops_nothing(self):
        """A dry run only lists the schemas."""
        self.run_cleanup(dry_run=True).assert_not_called()
