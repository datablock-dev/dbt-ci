"""Synapse migration SQL.

Only Synapse is migrated here. Its distribution and index are fixed when the table is
created, and it supports both CTAS and RENAME OBJECT, so the rows can be carried across.
Azure SQL Database (dbt-sqlserver) has no distribution configuration to migrate, and
Fabric Warehouse does not support the rename step, so both are reported as no-ops.
"""
from __future__ import annotations

import logging

from dbt_ci.connectors.generic.sql import quote_identifier, quote_relation
from dbt_ci.schema import MigrationMapNodeEntry

logger = logging.getLogger(__name__)

MIGRATION_SUFFIX = "__dbt_ci_migration"

DEFAULT_DISTRIBUTION = "ROUND_ROBIN"
DEFAULT_INDEX = "CLUSTERED COLUMNSTORE INDEX"


def render_table_options(config: dict) -> str:
    """Render the WITH (...) clause carrying a Synapse table's distribution and index."""
    # dbt-synapse passes these through into the DDL verbatim, so they are used as written.
    distribution = config.get("dist") or DEFAULT_DISTRIBUTION
    index = config.get("index") or DEFAULT_INDEX
    return f"WITH (DISTRIBUTION = {distribution}, {index})"


def plan_synapse_migration(node: MigrationMapNodeEntry, adapter_type: str) -> list[str]:
    """
    Render the statements that move a Synapse table onto its new distribution and index.

    Both are fixed at creation, so the rows are written into a new table carrying the new
    options, the original is dropped and the copy renamed into its place.
    """
    table_id = node["table_id"]
    relation = quote_relation(table_id, adapter_type)
    staging_table_id = f"{table_id}{MIGRATION_SUFFIX}"
    staging_relation = quote_relation(staging_table_id, adapter_type)
    # RENAME OBJECT takes a bare name for the target, not a qualified path.
    target_name = quote_identifier(table_id.split(".")[-1], adapter_type)

    if not node.get("new_config"):
        return []

    return [
        # Step 1: write the rows into a table carrying the new distribution and index.
        f"CREATE TABLE {staging_relation} {render_table_options(node['new_config'])} "
        f"AS SELECT * FROM {relation}",
        # Step 2: drop the original, whose options are fixed at creation time.
        f"DROP TABLE {relation}",
        # Step 3: give the copy the original's name.
        f"RENAME OBJECT {staging_relation} TO {target_name}",
    ]
