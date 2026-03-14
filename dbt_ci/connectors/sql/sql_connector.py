"""Generic SQLAlchemy-based SQL connector for dbt CI."""
import logging
import click
from sqlalchemy import Engine, text
from sqlalchemy.schema import CreateSchema, DropSchema

logger = logging.getLogger(__name__)


class SqlConnector:
    """
    Generic SQL connector using SQLAlchemy.

    Supports any SQLAlchemy-compatible dialect (PostgreSQL, MySQL, etc.).
    In SQL terms, a 'dataset' maps to a schema (PostgreSQL) or a
    database/schema (MySQL).
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def query(self, sql: str) -> list[dict]:
        """Execute a SQL query and return results as a list of row dicts."""
        with self.engine.connect() as conn:
            result = conn.execute(text(sql))
            return [dict(row._mapping) for row in result]

    def create_datasets(self, schemas: set[str], dry_run: bool = False) -> None:
        """Create schemas (datasets) if they do not already exist."""
        if not schemas:
            click.echo("No schemas to create.")
            return
        click.echo("Creating schemas:")
        for schema in schemas:
            click.echo(f"  - {schema}")
        if dry_run:
            click.echo("Dry run mode — no schemas will be created.")
            return
        with self.engine.connect() as conn:
            for schema in schemas:
                try:
                    conn.execute(CreateSchema(schema, if_not_exists=True))
                    conn.commit()
                    click.echo(f"Schema '{schema}' created.")
                except Exception as e:
                    raise RuntimeError(f"Failed to create schema '{schema}': {e}")

    def delete_datasets(self, schemas: set[str], dry_run: bool = False) -> None:
        """Drop schemas (datasets), including all their contents."""
        if not schemas:
            click.echo("No schemas to delete.")
            return
        click.echo("Deleting schemas:")
        for schema in schemas:
            click.echo(f"  - {schema}")
        if dry_run:
            click.echo("Dry run mode — no schemas will be deleted.")
            return
        # MySQL does not support CASCADE on DROP SCHEMA
        cascade = self.engine.dialect.name != "mysql"
        with self.engine.connect() as conn:
            for schema in schemas:
                try:
                    conn.execute(DropSchema(schema, cascade=cascade, if_exists=True))
                    conn.commit()
                    click.echo(f"Schema '{schema}' deleted.")
                except Exception as e:
                    raise RuntimeError(f"Failed to delete schema '{schema}': {e}")

    def create_tables(self, table_sqls: dict[str, str], dry_run: bool = False) -> None:
        """
        Execute CREATE TABLE statements.

        Args:
            table_sqls: Mapping of table identifier (for logging) to a CREATE TABLE SQL string.
            dry_run: If True, log what would be created without executing.
        """
        if not table_sqls:
            click.echo("No tables to create.")
            return
        click.echo("Creating tables:")
        for table_id in table_sqls:
            click.echo(f"  - {table_id}")
        if dry_run:
            click.echo("Dry run mode — no tables will be created.")
            return
        with self.engine.connect() as conn:
            for table_id, sql in table_sqls.items():
                try:
                    conn.execute(text(sql))
                    conn.commit()
                    click.echo(f"Table '{table_id}' created.")
                except Exception as e:
                    raise RuntimeError(f"Failed to create table '{table_id}': {e}")

    def delete_tables(self, table_ids: set[str], dry_run: bool = False) -> None:
        """Drop tables if they exist."""
        if not table_ids:
            click.echo("No tables to delete.")
            return
        click.echo("Deleting tables:")
        for table_id in table_ids:
            click.echo(f"  - {table_id}")
        if dry_run:
            click.echo("Dry run mode — no tables will be deleted.")
            return
        prep = self.engine.dialect.identifier_preparer
        with self.engine.connect() as conn:
            for table_id in table_ids:
                # Quote each part of a schema.table identifier separately
                parts = table_id.split(".", 1)
                quoted = ".".join(prep.quote(part) for part in parts)
                try:
                    conn.execute(text(f"DROP TABLE IF EXISTS {quoted}"))
                    conn.commit()
                    click.echo(f"Table '{table_id}' deleted.")
                except Exception as e:
                    raise RuntimeError(f"Failed to delete table '{table_id}': {e}")
