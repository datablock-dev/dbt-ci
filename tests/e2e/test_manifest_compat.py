"""
Contract test for the parts of manifest.json that dbt-ci depends on.

dbt-ci reads node ids, resource types, file paths, configs and the parent/child maps
from the manifest. If a dbt version writes any of these differently, change detection
can degrade silently (e.g. git paths stop matching nodes) rather than fail loudly, so
this test compiles a small project with a real dbt binary and checks each field.

Opt-in like the other e2e tests: set DBT_CI_E2E_DBT_BINARY to a dbt executable that can
run DuckDB (dbt-core with dbt-duckdb, or dbt v2).
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

from dbt_ci.graph.graph_utils import get_nodes_from_path
from dbt_ci.graph.parser import generate_dependency_graph
from dbt_ci.schema import MANIFEST_KEY_MAPPING

DBT_BINARY = os.environ.get("DBT_CI_E2E_DBT_BINARY")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.requires_dbt,
    pytest.mark.skipif(not DBT_BINARY, reason="DBT_CI_E2E_DBT_BINARY is not set"),
]

PROJECT_FILES = {
    "dbt_project.yml": (
        "name: demo\nversion: 1.0.0\nprofile: demo\n"
        'model-paths: ["models"]\nseed-paths: ["seeds"]\nmacro-paths: ["macros"]\n'
        'test-paths: ["tests"]\n'
    ),
    "seeds/raw.csv": "id,name\n1,a\n2,b\n",
    "macros/upper_name.sql": "{% macro upper_name(col) %}upper({{ col }}){% endmacro %}\n",
    "models/stg.sql": "select id, {{ upper_name('name') }} as name from {{ ref('raw') }}\n",
    "models/agg.sql": (
        "{{ config(materialized='table') }}\n"
        "select count(*) as n from {{ ref('stg') }}\n"
    ),
    "models/from_source.sql": "select * from {{ source('ext', 'events') }}\n",
    "models/schema.yml": (
        "version: 2\n"
        "sources:\n"
        "  - name: ext\n"
        "    schema: main\n"
        "    tables:\n"
        "      - name: events\n"
        "models:\n"
        "  - name: stg\n"
        "    columns:\n"
        "      - name: id\n"
        "        data_tests: [not_null]\n"
        "exposures:\n"
        "  - name: dashboard\n"
        "    type: dashboard\n"
        "    owner: {name: ci, email: ci@example.com}\n"
        "    depends_on: [ref('agg')]\n"
    ),
    "tests/assert_positive.sql": "select * from {{ ref('agg') }} where n < 0\n",
}


@pytest.fixture(scope="module")
def compiled(tmp_path_factory) -> tuple[Path, dict]:
    """Compile the project with the dbt binary under test and return (project dir, manifest)."""
    root = tmp_path_factory.mktemp("manifest_compat")
    project = root / "dbt"
    for relative, content in PROJECT_FILES.items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    (project / "profiles.yml").write_text(
        "demo:\n  target: dev\n  outputs:\n"
        f"    dev: {{type: duckdb, path: '{root / 'dev.duckdb'}'}}\n"
    )

    result = subprocess.run(
        [str(DBT_BINARY), "compile", "--project-dir", str(project), "--profiles-dir", str(project)],
        cwd=project, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    manifest = json.loads((project / "target" / "manifest.json").read_text())
    return project, manifest


def project_entries(manifest: dict) -> dict[str, dict]:
    """Return every tracked manifest entry that belongs to the demo project."""
    entries: dict[str, dict] = {}
    for section in set(MANIFEST_KEY_MAPPING.values()):
        for unique_id, entry in (manifest.get(section) or {}).items():
            if unique_id.split(".")[0] in MANIFEST_KEY_MAPPING and ".demo." in unique_id:
                entries[unique_id] = entry
    return entries


def test_metadata_is_a_mapping(compiled):
    """The graph keeps manifest metadata as-is, so it must be a mapping."""
    _, manifest = compiled
    assert isinstance(manifest.get("metadata"), dict)


def test_expected_nodes_are_present(compiled):
    """Each resource type dbt-ci tracks is written under its unique_id."""
    _, manifest = compiled
    entries = project_entries(manifest)
    for unique_id in (
        "seed.demo.raw",
        "model.demo.stg",
        "model.demo.agg",
        "model.demo.from_source",
        "source.demo.ext.events",
        "exposure.demo.dashboard",
        "macro.demo.upper_name",
    ):
        assert unique_id in entries, sorted(entries)
    assert any(uid.startswith("test.demo.not_null_stg_id") for uid in entries), sorted(entries)
    assert "test.demo.assert_positive" in entries, sorted(entries)


def test_entries_have_the_fields_dbt_ci_reads(compiled):
    """name, resource_type and a project-relative original_file_path on every entry."""
    project, manifest = compiled
    for unique_id, entry in project_entries(manifest).items():
        assert isinstance(entry.get("name"), str), unique_id
        assert entry.get("resource_type") == unique_id.split(".")[0], unique_id

        path = entry.get("original_file_path")
        assert isinstance(path, str), unique_id
        # git reports paths relative to the project dir; anything else stops matching.
        assert not os.path.isabs(path) and not path.startswith("./"), (unique_id, path)
        assert "\\" not in path, (unique_id, path)
        assert (project / path).is_file(), (unique_id, path)


def test_models_carry_config_and_relation_fields(compiled):
    """Configs drive materialization checks; database/schema drive delete and clone."""
    _, manifest = compiled
    for unique_id in ("model.demo.stg", "model.demo.agg"):
        node = manifest["nodes"][unique_id]
        assert isinstance(node.get("config"), dict), unique_id
        assert isinstance(node["config"].get("materialized"), str), unique_id
        assert isinstance(node.get("schema"), str), unique_id
        assert isinstance(node.get("fqn"), list), unique_id
        assert isinstance(node.get("depends_on"), dict), unique_id
    assert manifest["nodes"]["model.demo.agg"]["config"]["materialized"] == "table"


def test_dependency_graph_resolves_lineage(compiled):
    """Parent/child maps and depends_on yield the expected lineage in dbt-ci's graph."""
    _, manifest = compiled
    graph = generate_dependency_graph(manifest)

    stg = graph["model"]["model.demo.stg"]
    assert "seed.demo.raw" in stg["upstream_dependencies"]["node_dependencies"]
    assert "macro.demo.upper_name" in stg["upstream_dependencies"]["dependencies_by_type"]["macro"]
    assert "model.demo.agg" in stg["downstream_dependencies"]["node_dependencies"]
    assert "exposure.demo.dashboard" in stg["indirect_downstream_dependencies"]["node_dependencies"]

    from_source = graph["model"]["model.demo.from_source"]
    assert "source.demo.ext.events" in from_source["upstream_dependencies"]["node_dependencies"]


def test_git_paths_map_to_nodes(compiled):
    """A changed file, as git reports it, resolves to the nodes defined in it."""
    _, manifest = compiled
    graph = generate_dependency_graph(manifest)

    def ids_at(path: str) -> set[str]:
        """Return the ids of graph nodes defined at a project-relative path."""
        return {node["id"] for node in get_nodes_from_path(graph, path)}

    assert ids_at("models/stg.sql") == {"model.demo.stg"}
    assert ids_at("seeds/raw.csv") == {"seed.demo.raw"}
    assert "macro.demo.upper_name" in ids_at("macros/upper_name.sql")
    assert "test.demo.assert_positive" in ids_at("tests/assert_positive.sql")

    schema_ids = ids_at("models/schema.yml")
    assert any(uid.startswith("test.demo.not_null_stg_id") for uid in schema_ids), schema_ids
    assert "source.demo.ext.events" in schema_ids, schema_ids
    assert "exposure.demo.dashboard" in schema_ids, schema_ids
