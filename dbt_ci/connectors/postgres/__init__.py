"""PostgreSQL connector for dbt CI."""
import logging
from argparse import Namespace
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from dbt_ci.connectors.sql.sql_connector import SqlConnector
from dbt_ci.utilities.paths import get_profile

logger = logging.getLogger(__name__)

def postgres_client(args: Namespace) -> SqlConnector:
    """Create a SqlConnector for PostgreSQL using credentials from dbt profiles.yml.

    Supports both individual connection fields (host/port/user/password/dbname)
    and a DSN/connection string passed via the 'dsn' key.
    """
    output = get_profile(args)

    if output.get("type") != "postgres":
        raise ValueError(
            f"Profile output type is '{output.get('type')}', expected 'postgres'."
        )

    dsn = output.get("dsn")
    if dsn:
        # DSN is a full connection string, e.g. "postgresql://user:pass@host:5432/db"
        # Ensure the driver is psycopg2 if no explicit driver is specified.
        if dsn.startswith("postgres://"):
            dsn = dsn.replace("postgres://", "postgresql+psycopg2://", 1)
        elif dsn.startswith("postgresql://"):
            dsn = dsn.replace("postgresql://", "postgresql+psycopg2://", 1)
        engine = create_engine(dsn)
    else:
        url = URL.create(
            drivername="postgresql+psycopg2",
            username=output.get("user"),
            password=output.get("password"),
            host=output.get("host", "localhost"),
            port=int(output.get("port", 5432)),
            database=output.get("dbname") or output.get("database"),
        )
        engine = create_engine(url)

    return SqlConnector(engine)
