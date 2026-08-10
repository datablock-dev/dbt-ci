"""Unit tests for the generic (run-operation based) connector."""
import importlib
import json
import pytest
from argparse import Namespace
from unittest.mock import patch

from dbt_ci.connectors import NATIVE_CONNECTORS, get_connector, generic_db_connector
from dbt_ci.connectors.snowflake import snowflake_db_connector
from dbt_ci.connectors.generic.run_operation import run_operation
from dbt_ci.connectors.generic.sql import (
    get_relation_kind,
    quote_identifier,
    quote_relation,
    render_delete_statements,
    render_drop_statement,
)
from dbt_ci.connectors.generic.strategies import (
    generic_delete_strategy,
    generic_migration_strategy,
)


def make_args(**overrides) -> Namespace:
    """Build a Namespace with the attributes the runner plumbing expects."""
    defaults = {
        "runner": "local",
        "dbt_project_dir": "/dbt",
        "profiles_dir": None,
        "reference_state": "/dbt/.dbtstate",
        "target": "prod",
        "vars": None,
        "defer": True,
        "dry_run": False,
    }
    defaults.update(overrides)
    return Namespace(**defaults)


class TestSqlRendering:
    """Test warehouse-agnostic SQL rendering."""

    @pytest.mark.parametrize("adapter_type,expected", [
        ("bigquery", "`my_db`.`my_schema`.`my_table`"),
        ("databricks", "`my_db`.`my_schema`.`my_table`"),
        ("snowflake", '"my_db"."my_schema"."my_table"'),
        ("postgres", '"my_db"."my_schema"."my_table"'),
        ("sqlserver", "[my_db].[my_schema].[my_table]"),
        (None, '"my_db"."my_schema"."my_table"'),
    ])
    def test_quote_relation_per_adapter(self, adapter_type, expected):
        """Each adapter family gets its own identifier quoting."""
        assert quote_relation("my_db.my_schema.my_table", adapter_type) == expected

    def test_quote_relation_skips_missing_parts(self):
        """Adapters without a database level must not produce a leading dot."""
        assert quote_relation("None.my_schema.my_table", "postgres") == '"my_schema"."my_table"'
        assert quote_relation("..my_table", "postgres") == '"my_table"'

    def test_quote_relation_rejects_empty_relation(self):
        """A relation with no identifier parts is an error, not an empty statement."""
        with pytest.raises(ValueError):
            quote_relation("..", "postgres")

    def test_quote_identifier_rejects_embedded_quotes(self):
        """Identifiers that could break out of their quoting are refused."""
        with pytest.raises(ValueError):
            quote_identifier('my"table', "snowflake")

    @pytest.mark.parametrize("materialization,expected", [
        ("incremental", "TABLE"),
        ("table", "TABLE"),
        ("snapshot", "TABLE"),
        (None, "TABLE"),
        ("view", "VIEW"),
        ("materialized_view", "MATERIALIZED VIEW"),
    ])
    def test_relation_kind(self, materialization, expected):
        """The DDL object kind follows the dbt materialization."""
        assert get_relation_kind(materialization) == expected

    def test_render_drop_statement(self):
        """A drop statement quotes the relation for the target adapter."""
        assert render_drop_statement("db.sch.tbl", "view", "snowflake") == (
            'DROP VIEW IF EXISTS "db"."sch"."tbl"'
        )

    def test_render_delete_statements_includes_dbt_tmp_for_tables(self):
        """Tables also drop the staging relation a crashed dbt run can leave behind."""
        statements = render_delete_statements("db.sch.tbl", "incremental", "bigquery")
        assert statements == [
            "DROP TABLE IF EXISTS `db`.`sch`.`tbl`",
            "DROP TABLE IF EXISTS `db`.`sch`.`tbl__dbt_tmp`",
        ]

    def test_render_delete_statements_skips_dbt_tmp_for_views(self):
        """Views have no staging relation, and DROP TABLE against one errors."""
        statements = render_delete_statements("db.sch.v", "view", "postgres")
        assert statements == ['DROP VIEW IF EXISTS "db"."sch"."v"']


class TestRunOperation:
    """Test the dbt run-operation wrapper."""

    @patch('dbt_ci.connectors.generic.run_operation.run_dbt_command')
    def test_run_operation_builds_command(self, mock_run):
        """Macro arguments are passed as JSON, which dbt parses as its --args mapping."""
        run_operation(make_args(), "run_query", {"sql": "DROP TABLE IF EXISTS `a`.`b`.`c`"})

        command = mock_run.call_args.kwargs["command_args"]
        assert command[:2] == ["run-operation", "run_query"]
        args_value = command[command.index("--args") + 1]
        assert json.loads(args_value) == {"sql": "DROP TABLE IF EXISTS `a`.`b`.`c`"}

    @patch('dbt_ci.connectors.generic.run_operation.run_dbt_command')
    def test_run_operation_omits_unsupported_flags(self, mock_run):
        """A run-operation selects no nodes, so state and deferral flags are left off."""
        run_operation(make_args(), "run_query", {"sql": "SELECT 1"})

        command = mock_run.call_args.kwargs["command_args"]
        assert "--state" not in command
        assert "--defer" not in command
        assert "--project-dir" in command
        assert command[command.index("--target") + 1] == "prod"


class TestGenericDeleteStrategy:
    """Test the generic delete strategy."""

    @patch('dbt_ci.connectors.generic.strategies.execute_statements')
    @patch('dbt_ci.connectors.generic.strategies.get_profile')
    def test_delete_renders_statements_per_node(self, mock_profile, mock_execute):
        """Every node in the delete map becomes adapter-appropriate DDL."""
        mock_profile.return_value = {"type": "snowflake"}
        delete_map = {
            "model.project.old_model": {
                "type": "model",
                "name": "old_model",
                "table_id": "db.sch.old_model",
                "materialization": "incremental",
            },
            "model.project.old_view": {
                "type": "model",
                "name": "old_view",
                "table_id": "db.sch.old_view",
                "materialization": "view",
            },
        }

        generic_delete_strategy(delete_map, make_args())

        statements = mock_execute.call_args[0][1]
        assert statements == [
            'DROP TABLE IF EXISTS "db"."sch"."old_model"',
            'DROP TABLE IF EXISTS "db"."sch"."old_model__dbt_tmp"',
            'DROP VIEW IF EXISTS "db"."sch"."old_view"',
        ]

    @patch('dbt_ci.connectors.generic.strategies.execute_statements')
    @patch('dbt_ci.connectors.generic.strategies.get_profile')
    def test_delete_dry_run_executes_nothing(self, mock_profile, mock_execute):
        """A dry run reports the DDL without issuing it."""
        mock_profile.return_value = {"type": "postgres"}
        delete_map = {
            "model.project.old_model": {
                "type": "model",
                "name": "old_model",
                "table_id": "db.sch.old_model",
                "materialization": "table",
            }
        }

        generic_delete_strategy(delete_map, make_args(dry_run=True))

        mock_execute.assert_not_called()

    @patch('dbt_ci.connectors.generic.strategies.execute_statements')
    @patch('dbt_ci.connectors.generic.strategies.get_profile')
    def test_delete_with_empty_map_executes_nothing(self, mock_profile, mock_execute):
        """An empty delete map is a no-op rather than an empty dbt invocation."""
        mock_profile.return_value = {"type": "postgres"}

        generic_delete_strategy({}, make_args())

        mock_execute.assert_not_called()


class TestGenericMigrationStrategy:
    """Test the generic migration strategy."""

    @patch('dbt_ci.connectors.generic.strategies.run_dbt_command')
    @patch('dbt_ci.connectors.generic.strategies.execute_statements')
    @patch('dbt_ci.connectors.generic.strategies.get_profile')
    def test_migration_drops_then_full_refreshes(self, mock_profile, mock_execute, mock_run):
        """The relation is dropped, then rebuilt by dbt with the new physical layout."""
        mock_profile.return_value = {"type": "snowflake"}
        migration_map = {
            "connector": "snowflake",
            "nodes": {
                "model.project.model1": {
                    "name": "model1",
                    "materialization": "incremental",
                    "table_id": "db.sch.model1",
                    "compiled_code": "SELECT 1",
                    "old_partitioning": None,
                    "new_partitioning": None,
                    "old_config": {"cluster_by": ["a"]},
                    "new_config": {"cluster_by": ["b"]},
                }
            },
        }

        generic_migration_strategy(migration_map, make_args())

        assert mock_execute.call_args[0][1] == ['DROP TABLE IF EXISTS "db"."sch"."model1"']
        command = mock_run.call_args.kwargs["command_args"]
        assert command[:2] == ["run", "--full-refresh"]
        assert command[command.index("--select") + 1] == "model1"

    @patch('dbt_ci.connectors.generic.strategies.run_dbt_command')
    @patch('dbt_ci.connectors.generic.strategies.execute_statements')
    @patch('dbt_ci.connectors.generic.strategies.get_profile')
    def test_migration_dry_run_changes_nothing(self, mock_profile, mock_execute, mock_run):
        """A dry run neither drops nor rebuilds."""
        mock_profile.return_value = {"type": "snowflake"}
        migration_map = {
            "connector": "snowflake",
            "nodes": {
                "model.project.model1": {
                    "name": "model1",
                    "materialization": "incremental",
                    "table_id": "db.sch.model1",
                    "compiled_code": None,
                    "old_partitioning": None,
                    "new_partitioning": None,
                }
            },
        }

        generic_migration_strategy(migration_map, make_args(dry_run=True))

        mock_execute.assert_not_called()
        mock_run.assert_not_called()


class TestConnectorResolution:
    """Test which connector an adapter type resolves to."""

    def test_adapter_without_a_native_connector_uses_the_generic_one(self):
        """Adapters dbt-ci ships no native connector for are served by the generic one."""
        for adapter_type in ("duckdb", "trino", "athena"):
            assert get_connector(adapter_type) is generic_db_connector

    def test_native_connector_is_used_when_its_driver_is_installed(self):
        """With the extra installed, the native connector wins."""
        with patch('dbt_ci.connectors.snowflake.is_available', return_value=True):
            connector = get_connector("snowflake")
        assert connector is snowflake_db_connector

    def test_missing_driver_falls_back_instead_of_failing(self):
        """A native connector whose extra is absent must not break the command."""
        with patch('dbt_ci.connectors.snowflake.is_available', return_value=False):
            connector = get_connector("snowflake")
        assert connector is generic_db_connector

    def test_bigquery_keeps_its_native_connector(self):
        """BigQuery keeps its warehouse-native, data-preserving implementation."""
        with patch('dbt_ci.connectors.google.is_available', return_value=True):
            connector = get_connector("bigquery")
        assert connector is not generic_db_connector
        assert connector.get("client") is not None

    def test_every_registered_native_connector_is_complete(self):
        """Each entry in the registry imports and satisfies both warehouse commands."""
        for adapter_type, native in NATIVE_CONNECTORS.items():
            module = importlib.import_module(native.module)
            connector = getattr(module, native.attribute, None)
            assert connector is not None, f"{adapter_type} names a missing connector"
            assert connector["client"] is not None, adapter_type
            assert connector["strategies"]["delete"] is not None, adapter_type
            assert connector["strategies"]["migration"] is not None, adapter_type

    def test_generic_connector_implements_both_strategies(self):
        """The generic connector satisfies the delete and migration commands."""
        assert generic_db_connector["strategies"]["delete"] is not None
        assert generic_db_connector["strategies"]["migration"] is not None
