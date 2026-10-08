"""Unit tests for the BigQuery connector."""
from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest

from dbt_ci.connectors.google.bigquery import bigquery_client, bigquery_delete_strategy

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

    def test_missing_profile_key_raises(self, bigquery_project, mock_bigquery):
        """A dbt_project.yml without a profile key raises a clear error."""
        (bigquery_project / "dbt_project.yml").write_text("name: test_project\n")
        args = Namespace(dbt_project_dir=str(bigquery_project), profiles_dir=None, target="prod")

        with pytest.raises(ValueError, match="No 'profile' key found in dbt_project.yml"):
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
                "type": "model", "name": "orders", "table_id": "my-gcp-project.analytics.orders"
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

    def migrate(self, fail_on: str | None = None) -> list[str]:
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

        def run_all(func_list, threads, exit_on_exception):
            """Run the migration functions sequentially, re-raising errors."""
            for func in func_list:
                func()

        with patch("dbt_ci.connectors.google.bigquery.bigquery_client", return_value=client), \
             patch("dbt_ci.connectors.google.bigquery.get_profile", return_value={"threads": 1}), \
             patch("dbt_ci.connectors.google.bigquery.run_multithreaded", side_effect=run_all):
            bigquery_migration_strategy({"connector": "bigquery", "nodes": {"model.pkg.orders": self.NODE}}, Namespace(dry_run=False))
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


class TestMigrationTableId:
    """Test that the migration targets the relation dbt actually builds."""

    def test_alias_is_used(self):
        """A model with an alias is migrated under its alias, not its name."""
        from dbt_ci.commands.migration.index import generate_migration_map

        def node(partition):
            """Build an incremental model node aliased to 'orders'."""
            return {"id": "model.pkg.orders_v2", "name": "orders_v2", "alias": "orders", "resource_type": "model",
                    "database": "proj", "schema": "ana", "materialized": "incremental",
                    "config": {"materialized": "incremental", "partition_by": partition}}

        target = {"model": {"model.pkg.orders_v2": node({"field": "d", "data_type": "date"})}}
        reference = {"model": {"model.pkg.orders_v2": node(None)}}

        def make_graph(_args, is_reference=False):
            """Return the reference or target graph depending on the flag."""
            graph = MagicMock()
            graph.to_dict.return_value = reference if is_reference else target
            return graph

        cache = MagicMock()
        cache.get_cache.return_value = {"modified_nodes": {"model": {"model.pkg.orders_v2": {}}}}
        with patch("dbt_ci.commands.migration.index.DbtGraph", side_effect=make_graph), \
             patch("dbt_ci.commands.migration.index.get_profile", return_value={"type": "bigquery"}):
            migration_map = generate_migration_map(Namespace(), cache)
        assert migration_map["nodes"]["model.pkg.orders_v2"]["table_id"] == "proj.ana.orders"
