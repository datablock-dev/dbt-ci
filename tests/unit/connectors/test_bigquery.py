"""Unit tests for the BigQuery connector."""

from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest

from dbt_ci.connectors.google.bigquery import (
    bigquery_client,
    bigquery_delete_datasets,
    bigquery_delete_strategy,
    bigquery_delete_tables,
    render_bigquery_cluster_clause,
    render_bigquery_partition_clause,
)
from dbt_ci.errors import ConfigurationError

PROFILES_YML = """
bq_profile:
  target: prod
  outputs:
    prod:
      type: bigquery
      project: my-gcp-project
      location: EU
      threads: 2
"""


@pytest.fixture
def bigquery_project(temp_dir):
    """Create a dbt project whose profile points at a BigQuery output."""
    (temp_dir / "dbt_project.yml").write_text("name: test_project\nprofile: bq_profile\n")
    (temp_dir / "profiles.yml").write_text(PROFILES_YML)
    return temp_dir


@pytest.fixture
def mock_bigquery():
    """Replace the google.cloud.bigquery module so no real client is created."""
    with patch("dbt_ci.connectors.google.bigquery.bigquery") as module:
        yield module


class TestBigQueryClient:
    """Test BigQuery client creation from the dbt project and profiles."""

    def test_reads_profile_from_dbt_project_file(self, bigquery_project, mock_bigquery):
        """The profile name comes from dbt_project.yml; no `project` arg is needed."""
        args = Namespace(dbt_project_dir=str(bigquery_project), profiles_dir=None, target="prod")

        client = bigquery_client(args)

        mock_bigquery.Client.assert_called_once_with(project="my-gcp-project", location="EU")
        assert client is mock_bigquery.Client.return_value

    def test_missing_profile_key_falls_back_to_default(self, bigquery_project, mock_bigquery):
        """Without a profile key the 'default' profile is used, and its absence is reported."""
        (bigquery_project / "dbt_project.yml").write_text("name: test_project\n")
        args = Namespace(dbt_project_dir=str(bigquery_project), profiles_dir=None, target="prod")

        with pytest.raises(ConfigurationError, match="Profile 'default' not found"):
            bigquery_client(args)

    def test_profiles_dir_is_honoured(self, bigquery_project, mock_bigquery, tmp_path):
        """profiles.yml outside the project is found through --profiles-dir."""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (bigquery_project / "profiles.yml").rename(profiles_dir / "profiles.yml")
        args = Namespace(
            dbt_project_dir=str(bigquery_project), profiles_dir=str(profiles_dir), target=None
        )

        bigquery_client(args)

        mock_bigquery.Client.assert_called_once_with(project="my-gcp-project", location="EU")

    def test_non_bigquery_output_raises(self, bigquery_project, mock_bigquery):
        """A target that points at another warehouse cannot build a BigQuery client."""
        (bigquery_project / "profiles.yml").write_text(
            PROFILES_YML.replace("type: bigquery", "type: snowflake")
        )
        args = Namespace(dbt_project_dir=str(bigquery_project), profiles_dir=None, target="prod")

        with pytest.raises(ConfigurationError, match="target 'prod' is not 'bigquery'"):
            bigquery_client(args)


class TestBigQueryDeleteStrategy:
    """Test the delete strategy used by `dbt-ci delete`."""

    def test_deletes_tables_and_tmp_tables(self, bigquery_project, mock_bigquery):
        """Each table in the delete map and its __dbt_tmp table are deleted."""
        args = Namespace(
            dbt_project_dir=str(bigquery_project), profiles_dir=None, target="prod", dry_run=False
        )
        delete_map = {
            "model.test_project.orders": {
                "type": "model",
                "name": "orders",
                "table_id": "my-gcp-project.analytics.orders",
            }
        }

        bigquery_delete_strategy(delete_map, args)

        deleted = {c.args[0] for c in mock_bigquery.Client.return_value.delete_table.call_args_list}
        assert deleted == {
            "my-gcp-project.analytics.orders",
            "my-gcp-project.analytics.orders__dbt_tmp",
        }


class TestMigrationStrategy:
    """Test the SQL the partitioning migration runs, and that it never loses the original table."""

    NODE = {
        "table_id": "proj.ana.orders",
        "compiled_code": None,
        "old_partitioning": None,
        "new_partitioning": {"field": "created_at", "data_type": "date"},
        "cluster_by": ["customer_id", "status"],
        "require_partition_filter": True,
        "partition_expiration_days": 30,
    }

    def migrate(self, fail_on: str | None = None, dry_run: bool = False) -> list[str]:
        """Run the migration for one table and return the executed SQL statements."""
        from dbt_ci.connectors.google.bigquery import bigquery_migration_strategy

        executed: list[str] = []
        client = MagicMock()

        def query(sql):
            """Record a statement, optionally failing on one."""
            executed.append(sql)
            if fail_on and sql.startswith(fail_on):
                raise RuntimeError("rename failed")
            return MagicMock()

        client.query.side_effect = query

        def run_all(func_list, threads):
            """Run the migration functions sequentially, re-raising errors."""
            for func in func_list:
                func()

        with (
            patch("dbt_ci.connectors.google.bigquery.bigquery_client", return_value=client),
            patch("dbt_ci.connectors.google.bigquery.get_profile", return_value={"threads": 1}),
            patch("dbt_ci.connectors.google.bigquery.run_multithreaded", side_effect=run_all),
        ):
            bigquery_migration_strategy(
                {"connector": "bigquery", "nodes": {"model.pkg.orders": self.NODE}},
                Namespace(dry_run=dry_run),
            )
        return executed

    def test_copy_keeps_clustering_and_partition_options(self):
        """A plain CTAS dropped clustering and partition options."""
        create = self.migrate()[0]
        assert "PARTITION BY" in create
        assert "CLUSTER BY `customer_id`, `status`" in create
        assert "OPTIONS(require_partition_filter=true, partition_expiration_days=30.0)" in create

    def test_original_is_moved_aside_before_the_swap(self):
        """The original is renamed to a backup, and only dropped after the swap succeeded."""
        executed = self.migrate()
        assert executed[1] == "ALTER TABLE `proj.ana.orders` RENAME TO `orders__dbt_ci_backup`"
        assert executed[2] == "ALTER TABLE `proj.ana.orders_temp_new_partition` RENAME TO `orders`"
        assert executed[3] == "DROP TABLE IF EXISTS `proj.ana.orders__dbt_ci_backup`"
        assert "DROP TABLE IF EXISTS `proj.ana.orders`" not in executed

    def test_failed_swap_keeps_the_backup(self):
        """If the swap fails, the backup is not dropped and the error names it."""
        with pytest.raises(RuntimeError, match="orders__dbt_ci_backup"):
            self.migrate(fail_on="ALTER TABLE `proj.ana.orders_temp_new_partition`")

    def test_dry_run_runs_nothing(self):
        """A dry run lists the migration without touching any table."""
        assert self.migrate(dry_run=True) == []


class TestDeleteDatasets:
    """Ephemeral teardown drops whole datasets, contents included."""

    def test_each_dataset_is_dropped_with_its_contents(self):
        """Every dataset is deleted, and an already missing one is not an error."""
        client = MagicMock()

        bigquery_delete_datasets(client, {"proj.ci_pr_1", "proj.ci_pr_2"}, threads=2)

        assert sorted(c.args[0] for c in client.delete_dataset.call_args_list) == [
            "proj.ci_pr_1",
            "proj.ci_pr_2",
        ]
        for call in client.delete_dataset.call_args_list:
            assert call.kwargs == {"delete_contents": True, "not_found_ok": True}

    def test_failure_names_the_dataset(self):
        """A failed drop fails teardown, naming the dataset and keeping the cause."""
        client = MagicMock()
        cause = PermissionError("403")
        client.delete_dataset.side_effect = cause

        with pytest.raises(RuntimeError, match="proj.ci_pr_1") as exc_info:
            bigquery_delete_datasets(client, {"proj.ci_pr_1"})
        assert exc_info.value.__cause__ is cause

    def test_dry_run_drops_nothing(self):
        """A dry run only lists the datasets."""
        client = MagicMock()
        bigquery_delete_datasets(client, {"proj.ci_pr_1"}, dry_run=True)
        client.delete_dataset.assert_not_called()


def test_delete_tables_dry_run_drops_nothing():
    """`dbt-ci delete --dry-run` only lists the tables."""
    client = MagicMock()
    bigquery_delete_tables(client, {"proj.ana.orders"}, dry_run=True)
    client.delete_table.assert_not_called()


class TestPartitionClause:
    """The PARTITION BY clause matches what dbt-bigquery builds for each partition_by."""

    @pytest.mark.parametrize(
        "partition_by, expected",
        [
            ({"field": "d", "data_type": "date"}, "PARTITION BY d"),
            (
                {"field": "d", "data_type": "date", "granularity": "month"},
                "PARTITION BY date_trunc(d, month)",
            ),
            (
                {"field": "ts", "data_type": "timestamp", "granularity": "hour"},
                "PARTITION BY timestamp_trunc(ts, hour)",
            ),
            ({"field": "dt", "data_type": "datetime"}, "PARTITION BY datetime_trunc(dt, day)"),
            (
                {
                    "field": "id",
                    "data_type": "int64",
                    "range": {"start": 0, "end": 100, "interval": 10},
                },
                "PARTITION BY range_bucket(id, generate_array(0, 100, 10))",
            ),
            (
                {"field": "ts", "data_type": "timestamp", "time_ingestion_partitioning": True},
                "PARTITION BY timestamp_trunc(_PARTITIONTIME, day)",
            ),
            (None, ""),
            ({}, ""),
        ],
    )
    def test_rendering(self, partition_by, expected):
        """Each supported partition type renders its clause; no config renders none."""
        assert render_bigquery_partition_clause(partition_by) == expected

    @pytest.mark.parametrize(
        "partition_by, message",
        [
            ({"data_type": "date"}, "field is required"),
            ({"field": "d", "data_type": "string"}, "data_type must be one of"),
            (
                {"field": "d", "data_type": "date", "granularity": "hour"},
                "Date partitioning supports",
            ),
            ({"field": "id", "data_type": "int64"}, "range.start/end/interval required"),
        ],
    )
    def test_invalid_config_raises(self, partition_by, message):
        """A partition_by BigQuery cannot express fails before any table is touched."""
        with pytest.raises(ValueError, match=message):
            render_bigquery_partition_clause(partition_by)

    @pytest.mark.parametrize(
        "cluster_by, expected",
        [("a", "CLUSTER BY `a`"), (["a", "b"], "CLUSTER BY `a`, `b`"), (None, ""), ([], "")],
    )
    def test_cluster_clause(self, cluster_by, expected):
        """cluster_by may be one column or a list."""
        assert render_bigquery_cluster_clause(cluster_by) == expected


class TestMigrationTableId:
    """Test that the migration targets the relation dbt actually builds."""

    def test_alias_is_used(self):
        """A model with an alias is migrated under its alias, not its name."""
        from dbt_ci.commands.migration.index import generate_migration_map

        def node(partition):
            """Build an incremental model node aliased to 'orders'."""
            return {
                "id": "model.pkg.orders_v2",
                "name": "orders_v2",
                "alias": "orders",
                "resource_type": "model",
                "database": "proj",
                "schema": "ana",
                "materialized": "incremental",
                "config": {"materialized": "incremental", "partition_by": partition},
            }

        target = {"model": {"model.pkg.orders_v2": node({"field": "d", "data_type": "date"})}}
        reference = {"model": {"model.pkg.orders_v2": node(None)}}

        def make_graph(_args, is_reference=False):
            """Return the reference or target graph depending on the flag."""
            graph = MagicMock()
            graph.to_dict.return_value = reference if is_reference else target
            return graph

        cache = MagicMock()
        cache.get_cache.return_value = {"modified_nodes": {"model": {"model.pkg.orders_v2": {}}}}
        with (
            patch("dbt_ci.commands.migration.index.DbtGraph", side_effect=make_graph),
            patch("dbt_ci.commands.migration.index.get_profile", return_value={"type": "bigquery"}),
        ):
            migration_map = generate_migration_map(Namespace(), cache)
        assert migration_map["nodes"]["model.pkg.orders_v2"]["table_id"] == "proj.ana.orders"
