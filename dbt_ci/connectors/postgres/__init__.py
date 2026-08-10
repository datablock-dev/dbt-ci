"""Native Postgres connector.

dbt-postgres has no partitioning or clustering configuration - its only physical config is
`indexes`, which dbt creates itself on every build - so there is nothing for `migration` to
apply. The connector therefore implements `delete` and reports `migration` as a no-op.
"""
from __future__ import annotations

import logging
from argparse import Namespace
from typing import Any

from dbt_ci.schema import ConnectorConfig
from dbt_ci.connectors.dbapi import DbapiClient, build_delete_strategy, pick
from dbt_ci.connectors.dbapi.strategies import build_noop_migration_strategy
from dbt_ci.utilities.optional_imports import require
from dbt_ci.utilities.paths import get_profile

try:  # psycopg2-binary ships in the optional "postgres" extra.
    import psycopg2
except ImportError:  # pragma: no cover - exercised only without the extra installed
    psycopg2 = None

logger = logging.getLogger(__name__)

EXTRA = "postgres"


def build_connect_kwargs(profile: dict[str, Any]) -> dict[str, Any]:
    """Translate a dbt-postgres profile into psycopg2.connect() arguments."""
    database = pick(profile, "dbname", "database")
    if not database:
        raise ValueError("No 'dbname' specified for the Postgres target in profiles.yml")

    kwargs: dict[str, Any] = {
        "host": profile.get("host"),
        "port": profile.get("port", 5432),
        "dbname": database,
        "user": pick(profile, "user", "username"),
        "password": profile.get("password"),
        "sslmode": profile.get("sslmode"),
        "connect_timeout": profile.get("connect_timeout"),
    }

    # dbt applies search_path and role as connection options; mirror that so the drops
    # resolve the same relations dbt would.
    options = []
    if profile.get("search_path"):
        options.append(f"-c search_path={profile['search_path']}")
    if profile.get("role"):
        options.append(f"-c role={profile['role']}")
    if options:
        kwargs["options"] = " ".join(options)

    return {key: value for key, value in kwargs.items() if value is not None}


def postgres_client(args: Namespace) -> DbapiClient:
    """Create a Postgres client using the credentials from the dbt profile."""
    profile = get_profile(args)
    if profile.get("type") != "postgres":
        raise ValueError(f"Target profile type is '{profile.get('type')}', not 'postgres'.")

    driver = require(psycopg2, EXTRA, "The Postgres connector")
    kwargs = build_connect_kwargs(profile)

    return DbapiClient(
        connect=lambda: driver.connect(**kwargs),
        name="Postgres",
    )


postgres_db_connector: ConnectorConfig = {
    "client": postgres_client,
    "strategies": {
        "delete": build_delete_strategy(postgres_client),
        "migration": build_noop_migration_strategy(
            "Postgres has no partitioning or clustering configuration to migrate; indexes "
            "are rebuilt by dbt on every run."
        )
    }
}


def is_available() -> bool:
    """Report whether psycopg2 is installed, so the registry can fall back if not."""
    return psycopg2 is not None

__all__ = [
    "is_available",
    "postgres_client",
    "postgres_db_connector",
]
