"""Warehouse-agnostic SQL rendering for the generic connector."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Identifier quoting differs per warehouse. Anything not listed uses the ANSI double quote,
# which every SQL warehouse dbt supports accepts for quoted identifiers.
IDENTIFIER_QUOTES: dict[str, tuple[str, str]] = {
    "bigquery": ("`", "`"),
    "databricks": ("`", "`"),
    "spark": ("`", "`"),
    "hive": ("`", "`"),
    "mysql": ("`", "`"),
    "mariadb": ("`", "`"),
    "sqlserver": ("[", "]"),
    "synapse": ("[", "]"),
    "fabric": ("[", "]"),
}

DEFAULT_IDENTIFIER_QUOTES: tuple[str, str] = ('"', '"')

# Materializations whose relation is not a table, mapped to the object kind used in DDL.
NON_TABLE_RELATION_KINDS: dict[str, str] = {
    "view": "VIEW",
    "materialized_view": "MATERIALIZED VIEW",
}


def get_identifier_quotes(adapter_type: str | None) -> tuple[str, str]:
    """Return the (open, close) identifier quote characters used by a dbt adapter type."""
    return IDENTIFIER_QUOTES.get((adapter_type or "").lower(), DEFAULT_IDENTIFIER_QUOTES)


def quote_identifier(part: str, adapter_type: str | None = None) -> str:
    """Quote a single identifier for the given adapter type."""
    open_quote, close_quote = get_identifier_quotes(adapter_type)
    if open_quote in part or close_quote in part:
        raise ValueError(
            f"Identifier '{part}' contains a quote character and cannot be safely quoted "
            f"for adapter '{adapter_type}'."
        )
    return f"{open_quote}{part}{close_quote}"


def quote_relation(table_id: str, adapter_type: str | None = None) -> str:
    """
    Quote a dotted relation name (``database.schema.table``) part by part.

    Empty parts are dropped so adapters without a database level - where dbt leaves the
    database unset - do not produce a leading dot.
    """
    parts = [part for part in table_id.split(".") if part and part != "None"]
    if not parts:
        raise ValueError(f"Relation '{table_id}' does not contain any identifier parts.")
    return ".".join(quote_identifier(part, adapter_type) for part in parts)


def get_relation_kind(materialization: str | None) -> str:
    """Return the DDL object kind (``TABLE``, ``VIEW``, ...) backing a dbt materialization."""
    return NON_TABLE_RELATION_KINDS.get((materialization or "").lower(), "TABLE")


def render_drop_statement(
    table_id: str,
    materialization: str | None = None,
    adapter_type: str | None = None,
) -> str:
    """Render a ``DROP ... IF EXISTS`` statement for a relation."""
    return f"DROP {get_relation_kind(materialization)} IF EXISTS {quote_relation(table_id, adapter_type)}"


def render_delete_statements(
    table_id: str,
    materialization: str | None = None,
    adapter_type: str | None = None,
) -> list[str]:
    """
    Render every statement needed to remove a relation and its dbt leftovers.

    dbt's incremental and snapshot materializations stage data in a ``__dbt_tmp`` relation,
    which a crashed run can leave behind; it is dropped alongside the relation itself. Views
    have no such staging relation, and issuing ``DROP TABLE`` against a view errors on
    several warehouses, so nothing extra is emitted for them.
    """
    statements = [render_drop_statement(table_id, materialization, adapter_type)]
    if get_relation_kind(materialization) == "TABLE":
        statements.append(render_drop_statement(f"{table_id}__dbt_tmp", "table", adapter_type))
    return statements
