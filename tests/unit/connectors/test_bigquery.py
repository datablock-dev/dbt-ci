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
