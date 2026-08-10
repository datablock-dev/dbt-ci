"""Snowflake migration SQL."""
from __future__ import annotations

import logging

from dbt_ci.connectors.generic.sql import quote_relation
from dbt_ci.schema import MigrationMapNodeEntry

logger = logging.getLogger(__name__)


def as_cluster_expressions(cluster_by: object) -> list[str]:
    """
    Normalise dbt's cluster_by config into a list of clustering expressions.

    dbt-snowflake accepts either a single expression or a list of them.
    """
    if cluster_by is None:
        return []
    if isinstance(cluster_by, str):
        return [cluster_by]
    if isinstance(cluster_by, (list, tuple)):
        return [str(expression) for expression in cluster_by if expression]
    raise ValueError(f"Unsupported cluster_by configuration: {cluster_by!r}")


def plan_snowflake_migration(node: MigrationMapNodeEntry, adapter_type: str) -> list[str]:
    """
    Render the statements that move a Snowflake table onto its new clustering key.

    Snowflake changes a clustering key in place, so unlike BigQuery this neither rebuilds
    the table nor moves any data: the rows are untouched and the change is a metadata
    operation followed by background reclustering.
    """
    relation = quote_relation(node["table_id"], adapter_type)
    new_cluster_by = as_cluster_expressions(node.get("new_config", {}).get("cluster_by"))
    old_cluster_by = as_cluster_expressions(node.get("old_config", {}).get("cluster_by"))

    if new_cluster_by:
        return [f"ALTER TABLE {relation} CLUSTER BY ({', '.join(new_cluster_by)})"]

    if old_cluster_by:
        # Clustering was removed from the model config, so drop it from the table too.
        return [f"ALTER TABLE {relation} DROP CLUSTERING KEY"]

    return []
