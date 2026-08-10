"""Unit tests for the shared DBAPI client and strategy builders."""
import threading
from argparse import Namespace
from unittest.mock import MagicMock, patch

import duckdb

from dbt_ci.connectors.dbapi.client import DbapiClient, pick
from dbt_ci.connectors.dbapi.strategies import (
    build_delete_strategy,
    build_migration_strategy,
    build_noop_migration_strategy,
)


def make_args(**overrides) -> Namespace:
    """Build a Namespace with the attributes the strategies read."""
    defaults = {"dbt_project_dir": "/dbt", "dry_run": False}
    defaults.update(overrides)
    return Namespace(**defaults)


class FakeConnection:
    """A minimal PEP 249 connection recording the statements it was given."""

    def __init__(self, autocommit_supported=True):
        """Start with no statements executed and no commits."""
        self.statements = []
        self.commits = 0
        self.closed = False
        self._autocommit_supported = autocommit_supported
        if autocommit_supported:
            self.autocommit = False

    def __setattr__(self, name, value):
        """Refuse to set autocommit when emulating a driver that lacks it."""
        if name == "autocommit" and not getattr(self, "_autocommit_supported", True):
            raise AttributeError("autocommit is not supported")
        super().__setattr__(name, value)

    def cursor(self):
        """Return a cursor writing into this connection's statement log."""
        connection = self

        class FakeCursor:
            """Records executed statements and whether it was closed."""

            def execute(self, statement):
                """Record the statement."""
                connection.statements.append(statement)

            def close(self):
                """No-op close."""

        return FakeCursor()

    def commit(self):
        """Count an explicit commit."""
        self.commits += 1

    def close(self):
        """Mark the connection closed."""
        self.closed = True


class TestDbapiClient:
    """Test the shared PEP 249 wrapper."""

    def test_execute_sets_autocommit_and_skips_commit(self):
        """A driver that supports autocommit is not committed by hand."""
        connection = FakeConnection()
        client = DbapiClient(connect=lambda: connection, name="Fake")

        client.execute("DROP TABLE x")

        assert connection.statements == ["DROP TABLE x"]
        assert connection.autocommit is True
        assert connection.commits == 0

    def test_execute_commits_when_autocommit_unsupported(self):
        """A driver without a settable autocommit gets an explicit commit instead."""
        connection = FakeConnection(autocommit_supported=False)
        client = DbapiClient(connect=lambda: connection, name="Fake")

        client.execute("DROP TABLE x")

        assert connection.commits == 1

    def test_connection_is_reused_within_a_thread(self):
        """One connection per thread, not one per statement."""
        opened = []

        def connect():
            """Open and record a new connection."""
            connection = FakeConnection()
            opened.append(connection)
            return connection

        client = DbapiClient(connect=connect, name="Fake")
        client.execute_sequence(["A", "B", "C"])

        assert len(opened) == 1
        assert opened[0].statements == ["A", "B", "C"]

    def test_each_thread_gets_its_own_connection(self):
        """Concurrent statements must not share a connection across threads."""
        opened = []
        lock = threading.Lock()

        def connect():
            """Open and record a new connection."""
            connection = FakeConnection()
            with lock:
                opened.append(connection)
            return connection

        client = DbapiClient(connect=connect, name="Fake")
        client.execute_batch([f"DROP TABLE t{i}" for i in range(4)], threads=4)

        # Every statement ran, and no connection served more than its own thread's work.
        executed = sorted(s for connection in opened for s in connection.statements)
        assert executed == sorted(f"DROP TABLE t{i}" for i in range(4))

    def test_close_closes_every_connection(self):
        """close() releases the connections opened across all threads."""
        opened = []

        def connect():
            """Open and record a new connection."""
            connection = FakeConnection()
            opened.append(connection)
            return connection

        client = DbapiClient(connect=connect, name="Fake")
        client.execute("SELECT 1")
        client.close()

        assert all(connection.closed for connection in opened)

    def test_execute_sequences_keeps_each_sequence_ordered(self):
        """Steps for one relation must run in order even when relations run concurrently."""
        connections = []

        def connect():
            """Open and record a new connection."""
            connection = FakeConnection()
            connections.append(connection)
            return connection

        client = DbapiClient(connect=connect, name="Fake")
        client.execute_sequences([["A1", "A2", "A3"], ["B1", "B2", "B3"]], threads=2)

        for connection in connections:
            letters = {statement[0] for statement in connection.statements}
            for letter in letters:
                steps = [s for s in connection.statements if s.startswith(letter)]
                assert steps == sorted(steps)

    def test_against_a_real_dbapi_driver(self, tmp_path):
        """The wrapper drives an actual PEP 249 driver, not just the fake one."""
        database = str(tmp_path / "client.duckdb")
        setup = duckdb.connect(database)
        setup.execute("create table keep as select 1 as id")
        setup.execute("create table drop_me as select 1 as id")
        setup.close()

        client = DbapiClient(connect=lambda: duckdb.connect(database), name="DuckDB")
        client.execute('DROP TABLE IF EXISTS "drop_me"')
        client.close()

        check = duckdb.connect(database, read_only=True)
        tables = [row[0] for row in check.execute(
            "select table_name from information_schema.tables order by 1"
        ).fetchall()]
        check.close()
        assert tables == ["keep"]


class TestPick:
    """Test the profile key fallback helper."""

    def test_returns_first_present_key(self):
        """Adapters spell the same setting differently; the first match wins."""
        assert pick({"dbname": "a", "database": "b"}, "dbname", "database") == "a"
        assert pick({"database": "b"}, "dbname", "database") == "b"

    def test_returns_default_when_absent(self):
        """A missing key falls through to the default."""
        assert pick({}, "dbname", "database", default="fallback") == "fallback"


class TestStrategyBuilders:
    """Test the shared delete and migration strategy builders."""

    @patch('dbt_ci.connectors.dbapi.strategies.get_profile')
    def test_delete_strategy_drops_and_closes(self, mock_profile):
        """Delete renders adapter-appropriate DDL and always releases the client."""
        mock_profile.return_value = {"type": "snowflake", "threads": 2}
        client = MagicMock()
        delete_map = {
            "model.p.gone": {
                "type": "model",
                "name": "gone",
                "table_id": "db.sch.gone",
                "materialization": "table",
            }
        }

        build_delete_strategy(lambda args: client)(delete_map, make_args())

        statements = client.execute_batch.call_args[0][0]
        assert statements == [
            'DROP TABLE IF EXISTS "db"."sch"."gone"',
            'DROP TABLE IF EXISTS "db"."sch"."gone__dbt_tmp"',
        ]
        client.close.assert_called_once()

    @patch('dbt_ci.connectors.dbapi.strategies.get_profile')
    def test_delete_strategy_dry_run_opens_no_client(self, mock_profile):
        """A dry run must not connect to the warehouse at all."""
        mock_profile.return_value = {"type": "postgres"}
        factory = MagicMock()
        delete_map = {
            "model.p.gone": {
                "type": "model",
                "name": "gone",
                "table_id": "db.sch.gone",
                "materialization": "table",
            }
        }

        build_delete_strategy(factory)(delete_map, make_args(dry_run=True))

        factory.assert_not_called()

    @patch('dbt_ci.connectors.dbapi.strategies.get_profile')
    def test_migration_strategy_runs_one_sequence_per_node(self, mock_profile):
        """Each model's steps stay together as an ordered sequence."""
        mock_profile.return_value = {"type": "snowflake", "threads": 4}
        client = MagicMock()
        migration_map = {
            "connector": "snowflake",
            "nodes": {
                "model.p.a": {"table_id": "db.sch.a", "name": "a"},
                "model.p.b": {"table_id": "db.sch.b", "name": "b"},
            },
        }

        build_migration_strategy(
            lambda args: client,
            lambda node, adapter_type: [f"ALTER {node['name']} 1", f"ALTER {node['name']} 2"],
        )(migration_map, make_args())

        sequences = client.execute_sequences.call_args[0][0]
        assert sequences == [["ALTER a 1", "ALTER a 2"], ["ALTER b 1", "ALTER b 2"]]
        client.close.assert_called_once()

    @patch('dbt_ci.connectors.dbapi.strategies.get_profile')
    def test_migration_strategy_skips_nodes_with_no_plan(self, mock_profile):
        """A planner returning nothing leaves the warehouse untouched."""
        mock_profile.return_value = {"type": "snowflake"}
        factory = MagicMock()
        migration_map = {
            "connector": "snowflake",
            "nodes": {"model.p.a": {"table_id": "db.sch.a", "name": "a"}},
        }

        build_migration_strategy(factory, lambda node, adapter_type: [])(migration_map, make_args())

        factory.assert_not_called()

    @patch('dbt_ci.connectors.dbapi.strategies.get_profile')
    def test_noop_migration_strategy_succeeds(self, mock_profile):
        """Adapters with nothing to migrate report the reason instead of failing."""
        mock_profile.return_value = {"type": "postgres"}
        migration_map = {"connector": "postgres", "nodes": {"model.p.a": {"table_id": "db.sch.a"}}}

        # No exception and no exit: a red pipeline here would be misleading.
        build_noop_migration_strategy("nothing to do")(migration_map, make_args())
