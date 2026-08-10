"""Shared PEP 249 plumbing for the warehouse-native connectors.

Every adapter dbt-ci ships a native connector for - Snowflake, Redshift, Databricks,
the Azure SQL family, Postgres and MySQL - speaks DBAPI. Only the connection setup and
the DDL dialect differ, so both live in the per-adapter packages and everything else is
shared from here.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from dbt_ci.utilities.multi_threading import run_multithreaded

logger = logging.getLogger(__name__)


class DbapiClient:
    """
    A thin, thread-safe wrapper around a PEP 249 connection factory.

    DBAPI drivers vary in how much concurrency a single connection tolerates, so each
    worker thread gets its own connection rather than sharing one. Connections are opened
    lazily on first use and closed together by close().
    """

    def __init__(
        self,
        connect: Callable[[], Any],
        name: str,
        autocommit: bool = True,
    ):
        """Store the connection factory; nothing is opened until a statement runs."""
        self.connect = connect
        self.name = name
        self.autocommit = autocommit
        self._local = threading.local()
        self._connections: list[Any] = []
        self._lock = threading.Lock()

    def connection(self) -> Any:
        """Return this thread's connection, opening one if it has none yet."""
        existing = getattr(self._local, "connection", None)
        if existing is not None:
            return existing

        connection = self.connect()
        # Not every driver exposes autocommit as a settable attribute; those that do not
        # are committed explicitly after each statement instead.
        if self.autocommit:
            try:
                connection.autocommit = True
            except (AttributeError, TypeError):
                logger.debug(f"{self.name} driver does not support setting autocommit.")

        self._local.connection = connection
        with self._lock:
            self._connections.append(connection)
        return connection

    def execute(self, statement: str) -> None:
        """Execute a single statement, committing it if the driver is not autocommitting."""
        connection = self.connection()
        cursor = connection.cursor()
        try:
            logger.info(f"[{self.name}] {statement}")
            cursor.execute(statement)
            if not getattr(connection, "autocommit", False):
                connection.commit()
        finally:
            close_quietly(cursor, f"{self.name} cursor")

    def execute_sequence(self, statements: list[str]) -> None:
        """Execute statements in order on a single thread, stopping at the first failure."""
        for statement in statements:
            self.execute(statement)

    def execute_batch(self, statements: list[str], threads: int = 5) -> None:
        """Execute independent statements concurrently, one connection per worker."""
        if not statements:
            return
        run_multithreaded(
            func_list=[lambda statement=statement: self.execute(statement) for statement in statements],
            threads=threads,
            exit_on_exception=True
        )

    def execute_sequences(self, sequences: list[list[str]], threads: int = 5) -> None:
        """
        Execute several ordered statement sequences, running the sequences concurrently.

        Migrations are expressed this way: the steps for one table must not interleave,
        but two different tables can migrate at the same time.
        """
        if not sequences:
            return
        run_multithreaded(
            func_list=[lambda sequence=sequence: self.execute_sequence(sequence) for sequence in sequences],
            threads=threads,
            exit_on_exception=True
        )

    def close(self) -> None:
        """Close every connection this client opened."""
        with self._lock:
            connections, self._connections = self._connections, []
        for connection in connections:
            close_quietly(connection, f"{self.name} connection")


def close_quietly(closeable: Any, description: str) -> None:
    """Close a cursor or connection, logging rather than raising if it refuses."""
    try:
        closeable.close()
    except Exception as e:
        logger.debug(f"Failed to close {description}: {e}")


def pick(profile: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """
    Return the first key present and non-None in a dbt profile.

    dbt adapters spell the same idea differently - dbname vs database, server vs host,
    username vs user - and several accept more than one spelling themselves.
    """
    for key in keys:
        value = profile.get(key)
        if value is not None:
            return value
    return default
