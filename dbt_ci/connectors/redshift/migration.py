"""Redshift migration SQL."""
from __future__ import annotations

import logging

from dbt_ci.connectors.generic.sql import quote_identifier, quote_relation
from dbt_ci.schema import MigrationMapNodeEntry

logger = logging.getLogger(__name__)

# dist values that name a distribution style rather than a distribution key column.
DISTRIBUTION_STYLES = {"even", "all", "auto"}


def as_sort_columns(sort: object) -> list[str]:
    """Normalise dbt's sort config, which accepts a single column or a list of them."""
    if sort is None:
        return []
    if isinstance(sort, str):
        return [sort]
    if isinstance(sort, (list, tuple)):
        return [str(column) for column in sort if column]
    raise ValueError(f"Unsupported sort configuration: {sort!r}")


def render_diststyle_statement(relation: str, dist: object, adapter_type: str) -> str | None:
    """Render the ALTER DISTSTYLE statement for a new dist config, if one applies."""
    if dist is None:
        return None
    if not isinstance(dist, str):
        raise ValueError(f"Unsupported dist configuration: {dist!r}")

    if dist.lower() in DISTRIBUTION_STYLES:
        return f"ALTER TABLE {relation} ALTER DISTSTYLE {dist.upper()}"

    # Anything else names the column to distribute on.
    return f"ALTER TABLE {relation} ALTER DISTSTYLE KEY DISTKEY {quote_identifier(dist, adapter_type)}"


def render_sortkey_statement(
    relation: str,
    sort: object,
    sort_type: object,
    adapter_type: str,
    node_name: str,
) -> str | None:
    """Render the ALTER SORTKEY statement for a new sort config, if one applies."""
    columns = as_sort_columns(sort)
    resolved_sort_type = (sort_type or "compound").lower() if isinstance(sort_type, str) or sort_type is None else None

    if resolved_sort_type == "auto":
        return f"ALTER TABLE {relation} ALTER SORTKEY AUTO"

    if not columns:
        return f"ALTER TABLE {relation} ALTER SORTKEY NONE"

    if resolved_sort_type == "interleaved":
        # ALTER SORTKEY only produces compound keys, so applying it here would silently
        # change the sort type. Rebuilding the table is the only way to get an interleaved
        # key, which is dbt's job on a --full-refresh rather than ours.
        logger.warning(
            f"Model '{node_name}' requests an interleaved sort key, which Redshift cannot "
            "apply with ALTER SORTKEY. Rebuild it with 'dbt run --full-refresh' instead."
        )
        return None

    quoted = ", ".join(quote_identifier(column, adapter_type) for column in columns)
    return f"ALTER TABLE {relation} ALTER SORTKEY ({quoted})"


def plan_redshift_migration(node: MigrationMapNodeEntry, adapter_type: str) -> list[str]:
    """
    Render the statements that move a Redshift table onto its new sort and dist keys.

    Both are altered in place, so the rows are preserved and no rebuild happens; Redshift
    redistributes and re-sorts the table in the background.
    """
    relation = quote_relation(node["table_id"], adapter_type)
    new_config = node.get("new_config", {})
    old_config = node.get("old_config", {})
    node_name = node.get("name") or node["table_id"]
    statements: list[str] = []

    if new_config.get("dist") != old_config.get("dist"):
        statement = render_diststyle_statement(relation, new_config.get("dist"), adapter_type)
        if statement:
            statements.append(statement)

    if (new_config.get("sort"), new_config.get("sort_type")) != (old_config.get("sort"), old_config.get("sort_type")):
        statement = render_sortkey_statement(
            relation=relation,
            sort=new_config.get("sort"),
            sort_type=new_config.get("sort_type"),
            adapter_type=adapter_type,
            node_name=node_name,
        )
        if statement:
            statements.append(statement)

    return statements
