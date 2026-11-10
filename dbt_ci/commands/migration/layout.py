"""
Detect and apply changes to an incremental model's physical layout on any warehouse.

Each warehouse configures a table's layout with its own dbt config keys (partitioning on
BigQuery, clustering keys on Snowflake, sort and distribution keys on Redshift, ...).
An incremental model keeps its table between runs, so a change to those keys only
takes effect once the existing table is changed too.

BigQuery has a native connector (dbt_ci.connectors.google). For the other warehouses
the statements are rendered here and run through `dbt run-operation` (see
dbt_ci.dbt.operations), so no warehouse driver is needed and the connection is the one
in profiles.yml. Every statement keeps the table's rows:

- Snowflake changes a clustering key in place (ALTER TABLE ... CLUSTER BY).
- Redshift changes sort and distribution keys in place (ALTER SORTKEY / ALTER DISTSTYLE).
- Databricks changes liquid clustering in place (ALTER TABLE ... CLUSTER BY) and rewrites
  the table for partitioning and bucketing, which are fixed when a table is created, in
  one atomic CREATE OR REPLACE TABLE ... AS SELECT from the table itself.

Column names are written unquoted, as dbt writes them in the DDL it generates.
"""

from typing import Any

from dbt_ci.errors import DbtCiError

# The config keys that set a table's physical layout, per adapter type
LAYOUT_KEYS: dict[str, tuple[str, ...]] = {
    "bigquery": ("partition_by",),
    "snowflake": ("cluster_by",),
    "redshift": ("sort", "sort_type", "dist"),
    "databricks": ("partition_by", "clustered_by", "buckets", "liquid_clustered_by"),
}

# Adapters whose layout changes are applied with statements rendered here
SQL_ADAPTERS = ("snowflake", "redshift", "databricks")

# Redshift distribution styles; any other dist value names the distribution key column
DISTRIBUTION_STYLES = {"even", "all", "auto"}


class UnsupportedLayoutChange(DbtCiError):
    """A layout change that cannot be applied without rebuilding the table."""


def layout_change(
    adapter_type: str, new_config: dict[str, Any], old_config: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Return the old and new layout config when one of the adapter's layout keys changed."""
    keys = LAYOUT_KEYS.get(adapter_type, ())
    old = {key: old_config.get(key) for key in keys}
    new = {key: new_config.get(key) for key in keys}
    return (old, new) if old != new else None


def plan_statements(
    adapter_type: str,
    relation: str,
    old: dict[str, Any],
    new: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> list[str]:
    """
    Render the statements that move a table onto its new layout, keeping its rows.

    relation is the table as dbt renders it (the manifest's relation_name, already
    quoted). Raises UnsupportedLayoutChange for a change that needs a rebuild.
    """
    if adapter_type == "snowflake":
        return _snowflake(relation, old, new)
    if adapter_type == "redshift":
        return _redshift(relation, old, new)
    if adapter_type == "databricks":
        return _databricks(relation, old, new, config or {})
    raise UnsupportedLayoutChange(f"dbt-ci cannot change table layouts on {adapter_type}.")


def _columns(value: Any) -> list[str]:
    """Normalise a config that takes a single column or expression, or a list of them."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item]
    raise UnsupportedLayoutChange(f"Unsupported layout configuration: {value!r}")


def _snowflake(relation: str, old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Change the clustering key in place; the rows are reclustered in the background."""
    new_keys = _columns(new.get("cluster_by"))
    if new_keys:
        return [f"alter table {relation} cluster by ({', '.join(new_keys)})"]
    if _columns(old.get("cluster_by")):
        return [f"alter table {relation} drop clustering key"]
    return []


def _redshift(relation: str, old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Change distribution and sort keys in place; Redshift redistributes and re-sorts."""
    statements: list[str] = []
    dist = new.get("dist")
    if dist != old.get("dist") and dist is not None:
        if not isinstance(dist, str):
            raise UnsupportedLayoutChange(f"Unsupported dist configuration: {dist!r}")
        if dist.lower() in DISTRIBUTION_STYLES:
            statements.append(f"alter table {relation} alter diststyle {dist.lower()}")
        else:
            statements.append(f"alter table {relation} alter diststyle key distkey {dist}")

    sort_changed = (new.get("sort"), new.get("sort_type")) != (
        old.get("sort"),
        old.get("sort_type"),
    )
    if sort_changed:
        sort_type = str(new.get("sort_type") or "compound").lower()
        columns = _columns(new.get("sort"))
        if sort_type == "auto":
            statements.append(f"alter table {relation} alter sortkey auto")
        elif sort_type == "interleaved" and columns:
            # ALTER SORTKEY only makes compound keys; applying it would change the sort type
            raise UnsupportedLayoutChange(
                "Redshift cannot change a table to an interleaved sort key in place."
            )
        elif columns:
            statements.append(f"alter table {relation} alter sortkey ({', '.join(columns)})")
        else:
            statements.append(f"alter table {relation} alter sortkey none")
    return statements


def _databricks(
    relation: str, old: dict[str, Any], new: dict[str, Any], config: dict[str, Any]
) -> list[str]:
    """
    Change liquid clustering in place, or rewrite the table for partitioning and bucketing.

    Replacing a Delta table with a query on itself is atomic and keeps the table's
    history: until it commits, the old table is still there.
    """
    rewrite_keys = ("partition_by", "clustered_by", "buckets")
    if any(new.get(key) != old.get(key) for key in rewrite_keys):
        clauses = ["using delta"]
        partition_by = _columns(new.get("partition_by"))
        if partition_by:
            clauses.append(f"partitioned by ({', '.join(partition_by)})")
        clustered_by = _columns(new.get("clustered_by"))
        if clustered_by:
            if not new.get("buckets"):
                raise UnsupportedLayoutChange("clustered_by needs buckets on Databricks.")
            clauses.append(
                f"clustered by ({', '.join(clustered_by)}) into {int(new['buckets'])} buckets"
            )
        liquid = _columns(new.get("liquid_clustered_by"))
        if liquid:
            clauses.append(f"cluster by ({', '.join(liquid)})")
        properties = config.get("tblproperties")
        if isinstance(properties, dict) and properties:
            rendered = ", ".join(f"'{key}' = '{value}'" for key, value in properties.items())
            clauses.append(f"tblproperties ({rendered})")
        return [
            f"create or replace table {relation} {' '.join(clauses)} as select * from {relation}"
        ]

    liquid = _columns(new.get("liquid_clustered_by"))
    if liquid:
        return [f"alter table {relation} cluster by ({', '.join(liquid)})"]
    if _columns(old.get("liquid_clustered_by")):
        return [f"alter table {relation} cluster by none"]
    return []
