"""Tests for finding nodes whose config changed through dbt_project.yml."""

from dbt_ci.commands.init.project_config import (
    changed_project_config_keys,
    nodes_with_project_config_change,
    project_config_reason,
)

BASE = """
name: demo
vars:
  start: 2020
models:
  demo:
    +materialized: view
    staging:
      +schema: staging
      +meta: {owner: a}
    marts:
      materialized: table
seeds:
  demo:
    +column_types: {id: int}
"""


class TestChangedProjectConfigKeys:
    """Test which config keys a dbt_project.yml change touched."""

    def test_unchanged(self):
        """The same file changes nothing."""
        assert changed_project_config_keys(BASE, BASE) == set()

    def test_prefixed_unprefixed_and_mapping_values(self):
        """'+key', plain 'key' and mapping-valued '+key' configs are all compared."""
        head = (
            BASE.replace("+materialized: view", "+materialized: table")
            .replace("materialized: table\n", "materialized: incremental\n")
            .replace("{owner: a}", "{owner: b}")
        )
        assert changed_project_config_keys(BASE, head) == {"materialized", "meta"}

    def test_added_and_removed_configs(self):
        """A config added or removed counts as changed."""
        head = BASE.replace("      +schema: staging\n", "").replace(
            "    +column_types: {id: int}\n",
            "    +column_types: {id: int}\n    +quote_columns: true\n",
        )
        assert changed_project_config_keys(BASE, head) == {"schema", "quote_columns"}

    def test_other_sections_are_ignored(self):
        """vars and other top-level keys don't configure nodes this way."""
        head = BASE.replace("start: 2020", "start: 2021").replace("name: demo", "name: demo2")
        assert changed_project_config_keys(BASE, head) == set()

    def test_missing_or_invalid_files(self):
        """A file missing at the base counts every config as new; invalid YAML as empty."""
        assert "materialized" in changed_project_config_keys(None, BASE)
        assert changed_project_config_keys("models: [", "models: [") == set()


def _graph(configs: dict[str, dict]) -> dict:
    """A minimal dependency graph of models with the given configs."""
    return {
        "model": {
            node_id: {"id": node_id, "name": node_id.split(".")[-1], "config": config}
            for node_id, config in configs.items()
        }
    }


class TestNodesWithProjectConfigChange:
    """Test which nodes a changed config key affected."""

    def test_only_the_changed_keys_count(self):
        """A node differing only in a key dbt_project.yml didn't change is left out."""
        reference = _graph(
            {
                "model.demo.a": {"materialized": "view", "schema": "prod"},
                "model.demo.b": {"materialized": "table", "schema": "prod"},
                "model.demo.c": {"materialized": "view", "schema": "prod"},
            }
        )
        target = _graph(
            {
                "model.demo.a": {"materialized": "table", "schema": "prod"},
                # b only differs in schema, e.g. environment-specific config
                "model.demo.b": {"materialized": "table", "schema": "ci"},
                "model.demo.c": {"materialized": "view", "schema": "prod"},
                # New nodes are reported as new, not here
                "model.demo.new": {"materialized": "table"},
            }
        )
        found = nodes_with_project_config_change({"materialized"}, target, reference)
        assert found == {"model.demo.a": ["materialized"]}

    def test_no_keys(self):
        """Without changed keys nothing is looked at."""
        graph = _graph({"model.demo.a": {"materialized": "view"}})
        assert nodes_with_project_config_change(set(), graph, graph) == {}

    def test_reason(self):
        """The reason names the file and the keys."""
        assert project_config_reason(["materialized", "meta"]) == (
            "config in `dbt_project.yml` changed: `materialized`, `meta`"
        )
