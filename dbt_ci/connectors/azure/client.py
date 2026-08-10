"""Azure SQL family client construction from a dbt profile.

Covers dbt-sqlserver, dbt-synapse and dbt-fabric, which share a profile shape and reach the
server through ODBC. Unlike the other extras this one needs a system ODBC driver installed
alongside the Python package - pyodbc is only the binding.
"""
from __future__ import annotations

import logging
from argparse import Namespace
from typing import Any

from dbt_ci.connectors.dbapi.client import DbapiClient, pick
from dbt_ci.utilities.optional_imports import require
from dbt_ci.utilities.paths import get_profile

try:  # pyodbc ships in the optional "azure" extra.
    import pyodbc
except ImportError:  # pragma: no cover - exercised only without the extra installed
    pyodbc = None

logger = logging.getLogger(__name__)

EXTRA = "azure"

SUPPORTED_TYPES = {"sqlserver", "synapse", "fabric"}
DEFAULT_DRIVER = "ODBC Driver 18 for SQL Server"

# Authentication modes that carry no username or password of their own.
PASSWORDLESS_AUTHENTICATION = {"activedirectorymsi", "activedirectoryinteractive", "cli"}


def as_odbc_flag(value: Any, default: bool) -> str:
    """Render a boolean profile value the way an ODBC connection string expects it."""
    resolved = default if value is None else bool(value)
    return "yes" if resolved else "no"


def build_connection_string(profile: dict[str, Any]) -> str:
    """Translate a dbt SQL Server family profile into an ODBC connection string."""
    server = pick(profile, "server", "host")
    database = pick(profile, "database", "dbname")
    if not server:
        raise ValueError("No 'server' specified for the target in profiles.yml")
    if not database:
        raise ValueError("No 'database' specified for the target in profiles.yml")

    port = profile.get("port")
    parts = [
        f"DRIVER={{{profile.get('driver') or DEFAULT_DRIVER}}}",
        f"SERVER={server},{port}" if port else f"SERVER={server}",
        f"DATABASE={database}",
        # Driver 18 defaults Encrypt to yes; the profile still wins where it is set.
        f"Encrypt={as_odbc_flag(profile.get('encrypt'), default=True)}",
        f"TrustServerCertificate={as_odbc_flag(profile.get('trust_cert'), default=False)}",
    ]

    authentication = (profile.get("authentication") or "sql").lower()
    if authentication == "sql":
        user = pick(profile, "user", "username", "uid")
        password = profile.get("password")
        if not user or not password:
            raise ValueError(
                "SQL authentication needs both 'user' and 'password' in profiles.yml. Set "
                "them, or pick an 'authentication' method."
            )
        parts.extend([f"UID={user}", f"PWD={password}"])
    elif authentication == "activedirectoryserviceprincipal":
        # The service principal's id and secret travel in the UID/PWD fields.
        parts.extend([
            "Authentication=ActiveDirectoryServicePrincipal",
            f"UID={profile.get('client_id')}",
            f"PWD={profile.get('client_secret')}",
        ])
    elif authentication in PASSWORDLESS_AUTHENTICATION:
        parts.append(f"Authentication={profile.get('authentication')}")
    else:
        # ActiveDirectoryPassword and anything newer the driver understands.
        parts.append(f"Authentication={profile.get('authentication')}")
        user = pick(profile, "user", "username", "uid")
        if user:
            parts.append(f"UID={user}")
        if profile.get("password"):
            parts.append(f"PWD={profile['password']}")

    return ";".join(parts)


def azure_client(args: Namespace) -> DbapiClient:
    """Create a SQL Server family client using the credentials from the dbt profile."""
    profile = get_profile(args)
    if profile.get("type") not in SUPPORTED_TYPES:
        raise ValueError(
            f"Target profile type is '{profile.get('type')}', not one of {sorted(SUPPORTED_TYPES)}."
        )

    driver = require(pyodbc, EXTRA, "The Azure SQL connector")
    connection_string = build_connection_string(profile)

    return DbapiClient(
        connect=lambda: driver.connect(connection_string, autocommit=True),
        name=str(profile.get("type")).capitalize(),
    )
