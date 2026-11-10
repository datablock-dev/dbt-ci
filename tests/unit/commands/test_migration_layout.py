"""Tests for detecting and applying table layout changes on warehouses other than BigQuery."""

from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest

from dbt_ci.commands.migration.index import generate_migration_map, migrate_with_sql
from dbt_ci.commands.migration.layout import (
    UnsupportedLayoutChange,
    layout_change,
    plan_statements,
)
from dbt_ci.errors import DbtCiError

REL = '"DB"."SCH"."EVENTS"'


class TestLayoutChange:
    """Test which config keys count as a layout change, per warehouse."""

    def test_keys_per_warehouse(self):
        """Only the warehouse's own layout keys count."""
        assert layout_change("snowflake", {"cluster_by": ["a"]}, {}) == (
            {"cluster_by": None},
            {"cluster_by": ["a"]},
        )
        # partition_by means nothing to Snowflake
        assert layout_change("snowflake", {"partition_by": "a"}, {}) is None
        old, new = layout_change("redshift", {"sort": "a", "dist": "b"}, {"sort": "a"})
        assert new == {"sort": "a", "sort_type": None, "dist": "b"}
        assert old["dist"] is None
        assert layout_change("bigquery", {"partition_by": {"field": "d"}}, {}) is not None

    def test_warehouses_without_layout_config(self):
        """Postgres, DuckDB and others have no layout keys, so nothing is a change."""
        assert layout_change("postgres", {"partition_by": "a"}, {}) is None
        assert layout_change("duckdb", {"cluster_by": "a"}, {}) is None


class TestSnowflake:
    """Snowflake clustering keys change in place."""

    def test_set_change_and_drop(self):
        """A key is set from a string or list, and removed when the config is gone."""
        assert plan_statements("snowflake", REL, {}, {"cluster_by": "to_date(ts)"}) == [
            f"alter table {REL} cluster by (to_date(ts))"
        ]
        assert plan_statements("snowflake", REL, {}, {"cluster_by": ["a", "b"]}) == [
            f"alter table {REL} cluster by (a, b)"
        ]
        assert plan_statements("snowflake", REL, {"cluster_by": "a"}, {"cluster_by": None}) == [
            f"alter table {REL} drop clustering key"
        ]
        assert plan_statements("snowflake", REL, {}, {}) == []


class TestRedshift:
    """Redshift sort and distribution keys change in place."""

    def test_distribution(self):
        """A style is set by name; anything else is the distribution key column."""
        assert plan_statements("redshift", REL, {}, {"dist": "EVEN"}) == [
            f"alter table {REL} alter diststyle even"
        ]
        assert plan_statements("redshift", REL, {"dist": "all"}, {"dist": "customer_id"}) == [
            f"alter table {REL} alter diststyle key distkey customer_id"
        ]
        with pytest.raises(UnsupportedLayoutChange):
            plan_statements("redshift", REL, {}, {"dist": ["a"]})

    def test_sort_keys(self):
        """Compound keys, removal and AUTO are applied; interleaved keys need a rebuild."""
        assert plan_statements("redshift", REL, {}, {"sort": ["a", "b"]}) == [
            f"alter table {REL} alter sortkey (a, b)"
        ]
        assert plan_statements("redshift", REL, {"sort": "a"}, {"sort": None}) == [
            f"alter table {REL} alter sortkey none"
        ]
        assert plan_statements("redshift", REL, {"sort": "a"}, {"sort_type": "auto"}) == [
            f"alter table {REL} alter sortkey auto"
        ]
        with pytest.raises(UnsupportedLayoutChange, match="interleaved"):
            plan_statements("redshift", REL, {}, {"sort": ["a"], "sort_type": "interleaved"})

    def test_both_at_once(self):
        """Distribution goes first, then the sort key."""
        statements = plan_statements("redshift", REL, {}, {"dist": "a", "sort": "b"})
        assert statements == [
            f"alter table {REL} alter diststyle key distkey a",
            f"alter table {REL} alter sortkey (b)",
        ]


class TestDatabricks:
    """Liquid clustering changes in place; partitioning and bucketing rewrite the table."""

    def test_liquid_clustering_in_place(self):
        """CLUSTER BY changes without a rewrite, and NONE removes it."""
        rel = "`cat`.`sch`.`events`"
        assert plan_statements("databricks", rel, {}, {"liquid_clustered_by": ["a"]}) == [
            f"alter table {rel} cluster by (a)"
        ]
        assert plan_statements(
            "databricks", rel, {"liquid_clustered_by": "a"}, {"liquid_clustered_by": None}
        ) == [f"alter table {rel} cluster by none"]

    def test_partitioning_rewrites_the_table_from_itself(self):
        """One atomic statement keeps the rows and applies the new layout and properties."""
        rel = "`cat`.`sch`.`events`"
        statements = plan_statements(
            "databricks",
            rel,
            {"partition_by": "a"},
            {"partition_by": ["d"], "clustered_by": "id", "buckets": 4},
            {"tblproperties": {"delta.appendOnly": "true"}},
        )
        assert statements == [
            f"create or replace table {rel} using delta partitioned by (d) "
            "clustered by (id) into 4 buckets tblproperties ('delta.appendOnly' = 'true') "
            f"as select * from {rel}"
        ]

    def test_bucketing_needs_buckets(self):
        """clustered_by without buckets can't be applied."""
        with pytest.raises(UnsupportedLayoutChange, match="buckets"):
            plan_statements("databricks", "t", {}, {"clustered_by": "id"})

    def test_other_warehouses(self):
        """Warehouses without rendered SQL raise."""
        with pytest.raises(UnsupportedLayoutChange):
            plan_statements("postgres", "t", {}, {})


def _graph(nodes: dict) -> MagicMock:
    """A DbtGraph stand-in holding the given models."""
    graph = MagicMock()
    graph.to_dict.return_value = {"model": nodes}
    return graph


def _model(name: str, **config) -> dict:
    """A model node as the dependency graph holds it."""
    return {
        "id": f"model.p.{name}",
        "name": name,
        "resource_type": "model",
        "database": "DB",
        "schema": "SCH",
        "relation_name": f'"DB"."SCH"."{name.upper()}"',
        "config": {"materialized": "incremental", **config},
    }


class TestGenerateMigrationMap:
    """Test what generate_migration_map picks up on a non-BigQuery warehouse."""

    def test_snowflake_changes(self):
        """Changed incremental models count; new models and other materializations don't."""
        target = {
            "model.p.events": _model("events", cluster_by=["d"]),
            "model.p.view": {
                **_model("view", cluster_by=["d"]),
                "config": {"materialized": "view"},
            },
            "model.p.new": _model("new", cluster_by=["d"]),
        }
        reference = {
            "model.p.events": _model("events", cluster_by=["a"]),
            "model.p.view": _model("view"),
        }
        cache = MagicMock()
        cache.get_cache.return_value = {
            "modified_nodes": {"model": {node_id: {} for node_id in target}}
        }
        with (
            patch(
                "dbt_ci.commands.migration.index.DbtGraph",
                side_effect=lambda args, is_reference=False: _graph(
                    reference if is_reference else target
                ),
            ),
            patch(
                "dbt_ci.commands.migration.index.get_profile", return_value={"type": "snowflake"}
            ),
        ):
            migration_map = generate_migration_map(Namespace(), cache)

        assert list(migration_map["nodes"]) == ["model.p.events"]
        node = migration_map["nodes"]["model.p.events"]
        assert node["relation_name"] == '"DB"."SCH"."EVENTS"'
        assert node["old_layout"] == {"cluster_by": ["a"]}
        assert node["new_layout"] == {"cluster_by": ["d"]}


class TestMigrateWithSql:
    """Test planning and running the statements."""

    def _map(self, **nodes) -> dict:
        """A migration map with the given old/new layouts per model."""
        return {
            "connector": "snowflake",
            "nodes": {
                f"model.p.{name}": {
                    "table_id": f"DB.SCH.{name}",
                    "relation_name": f"DB.SCH.{name}",
                    "old_layout": old,
                    "new_layout": new,
                }
                for name, (old, new) in nodes.items()
            },
        }

    def test_runs_each_models_statements(self):
        """Each model's statements run through run-operation."""
        migration_map = self._map(a=({}, {"cluster_by": "x"}), b=({}, {"cluster_by": "y"}))
        with patch("dbt_ci.commands.migration.index.run_statements") as run:
            migrate_with_sql(Namespace(dry_run=False), "snowflake", migration_map)
        assert [call.args[1] for call in run.call_args_list] == [
            ["alter table DB.SCH.a cluster by (x)"],
            ["alter table DB.SCH.b cluster by (y)"],
        ]

    def test_dry_run_only_plans(self):
        """A dry run logs the statements and runs nothing."""
        with patch("dbt_ci.commands.migration.index.run_statements") as run:
            migrate_with_sql(
                Namespace(dry_run=True), "snowflake", self._map(a=({}, {"cluster_by": "x"}))
            )
        run.assert_not_called()

    def test_unsupported_change_stops_before_anything_runs(self):
        """One change needing a rebuild stops the command before any table is touched."""
        migration_map = {
            "connector": "redshift",
            "nodes": {
                "model.p.ok": {"table_id": "t1", "old_layout": {}, "new_layout": {"sort": "a"}},
                "model.p.bad": {
                    "table_id": "t2",
                    "old_layout": {},
                    "new_layout": {"sort": "a", "sort_type": "interleaved"},
                },
            },
        }
        with patch("dbt_ci.commands.migration.index.run_statements") as run:
            with pytest.raises(DbtCiError, match="model.p.bad"):
                migrate_with_sql(Namespace(dry_run=False), "redshift", migration_map)
        run.assert_not_called()
