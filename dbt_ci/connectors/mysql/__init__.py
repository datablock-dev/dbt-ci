"""Native MySQL connector.

dbt-mysql is community maintained and exposes no partitioning or clustering configuration,
so this connector implements `delete` and reports `migration` as a no-op. MySQL has no
database/schema split either: dbt leaves the database level unset and the schema names the
MySQL database, which the relation quoting already handles by dropping empty parts.
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

try:  # pymysql ships in the optional "mysql" extra.
    import pymysql
except ImportError:  # pragma: no cover - exercised only without the extra installed
    pymysql = None

logger = logging.getLogger(__name__)

EXTRA = "mysql"

# dbt-mysql and its MariaDB sibling both report themselves through the 'type' key.
SUPPORTED_TYPES = {"mysql", "mysql5", "mariadb"}


def build_connect_kwargs(profile: dict[str, Any]) -> dict[str, Any]:
    """Translate a dbt-mysql profile into pymysql.connect() arguments."""
    host = pick(profile, "server", "host")
    if not host:
        raise ValueError("No 'server' specified for the MySQL target in profiles.yml")

    kwargs: dict[str, Any] = {
        "host": host,
        "port": int(profile.get("port", 3306)),
        "user": pick(profile, "username", "user"),
        "password": profile.get("password"),
        # dbt-mysql uses 'schema' for what MySQL calls the database.
        "database": pick(profile, "database", "schema"),
        "connect_timeout": profile.get("connect_timeout"),
    }

    if profile.get("ssl_disabled") is False:
        kwargs["ssl"] = {}

    return {key: value for key, value in kwargs.items() if value is not None}


def mysql_client(args: Namespace) -> DbapiClient:
    """Create a MySQL client using the credentials from the dbt profile."""
    profile = get_profile(args)
    if profile.get("type") not in SUPPORTED_TYPES:
        raise ValueError(f"Target profile type is '{profile.get('type')}', not a MySQL type.")

    driver = require(pymysql, EXTRA, "The MySQL connector")
    kwargs = build_connect_kwargs(profile)

    return DbapiClient(
        connect=lambda: driver.connect(**kwargs),
        name="MySQL",
    )


mysql_db_connector: ConnectorConfig = {
    "client": mysql_client,
    "strategies": {
        "delete": build_delete_strategy(mysql_client),
        "migration": build_noop_migration_strategy(
            "MySQL has no partitioning or clustering configuration in dbt to migrate."
        )
    }
}


def is_available() -> bool:
    """Report whether pymysql is installed, so the registry can fall back if not."""
    return pymysql is not None

__all__ = [
    "is_available",
    "mysql_client",
    "mysql_db_connector",
]
