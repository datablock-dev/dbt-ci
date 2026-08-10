"""Databricks migration SQL."""
from __future__ import annotations

import logging

from dbt_ci.connectors.generic.sql import quote_identifier, quote_relation
from dbt_ci.schema import MigrationMapNodeEntry

logger = logging.getLogger(__name__)

# Suffix for the table holding the rebuilt data before it takes the original's name.
MIGRATION_SUFFIX = "__dbt_ci_migration"


def as_column_list(value: object) -> list[str]:
    """Normalise a dbt config that accepts either a single column or a list of them."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(column) for column in value if column]
    raise ValueError(f"Unsupported column configuration: {value!r}")


def render_layout_clauses(config: dict, adapter_type: str) -> str:
    """Render the PARTITIONED BY / CLUSTERED BY clauses for a CREATE TABLE ... AS SELECT."""
    clauses: list[str] = []

    partition_by = as_column_list(config.get("partition_by"))
    if partition_by:
        columns = ", ".join(quote_identifier(column, adapter_type) for column in partition_by)
        clauses.append(f"PARTITIONED BY ({columns})")

    clustered_by = as_column_list(config.get("clustered_by"))
    buckets = config.get("buckets")
    if clustered_by and buckets:
        columns = ", ".join(quote_identifier(column, adapter_type) for column in clustered_by)
        clauses.append(f"CLUSTERED BY ({columns}) INTO {int(buckets)} BUCKETS")
    elif clustered_by:
        logger.warning(
            "clustered_by is set without buckets, which Databricks requires; the bucketing "
            "clause was left out."
        )

    return " ".join(clauses)


def plan_liquid_clustering(relation: str, new_config: dict, old_config: dict, adapter_type: str) -> list[str]:
    """Render the in-place ALTER for a liquid clustering change, which preserves the data."""
    new_clustering = as_column_list(new_config.get("liquid_clustered_by"))
    old_clustering = as_column_list(old_config.get("liquid_clustered_by"))

    if new_clustering:
        columns = ", ".join(quote_identifier(column, adapter_type) for column in new_clustering)
        return [f"ALTER TABLE {relation} CLUSTER BY ({columns})"]

    if old_clustering:
        return [f"ALTER TABLE {relation} CLUSTER BY NONE"]

    return []


def plan_databricks_migration(node: MigrationMapNodeEntry, adapter_type: str) -> list[str]:
    """
    Render the statements that move a Databricks table onto its new physical layout.

    Liquid clustering is altered in place. Hive-style partitioning and bucketing are baked
    into the table at creation, so those changes are applied by writing the rows into a new
    table carrying the new layout, dropping the original and renaming the copy into its
    place - the data is preserved, but the table is rewritten in full.
    """
    table_id = node["table_id"]
    relation = quote_relation(table_id, adapter_type)
    new_config = dict(node.get("new_config", {}))
    old_config = dict(node.get("old_config", {}))

    # Liquid clustering is independent of the layout baked into the table, so it is applied
    # on its own whenever it is the only thing that changed.
    rewrite_keys = ("partition_by", "clustered_by", "buckets")
    needs_rewrite = any(new_config.get(key) != old_config.get(key) for key in rewrite_keys)
    if not needs_rewrite:
        return plan_liquid_clustering(relation, new_config, old_config, adapter_type)

    layout = render_layout_clauses(new_config, adapter_type)
    staging_table_id = f"{table_id}{MIGRATION_SUFFIX}"
    staging_relation = quote_relation(staging_table_id, adapter_type)

    statements = [
        # Step 1: write the rows into a table carrying the new layout.
        f"CREATE OR REPLACE TABLE {staging_relation} {layout} AS SELECT * FROM {relation}".replace("  ", " "),
        # Step 2: drop the original, whose layout is fixed at creation time.
        f"DROP TABLE IF EXISTS {relation}",
        # Step 3: give the copy the original's name.
        f"ALTER TABLE {staging_relation} RENAME TO {relation}",
    ]

    statements.extend(plan_liquid_clustering(relation, new_config, old_config, adapter_type))
    return statements
