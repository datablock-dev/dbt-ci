"""Databricks client construction from a dbt profile."""
from __future__ import annotations

import logging
from argparse import Namespace
from typing import Any

from dbt_ci.connectors.dbapi.client import DbapiClient, pick
from dbt_ci.utilities.optional_imports import require
from dbt_ci.utilities.paths import get_profile

try:  # databricks-sql-connector ships in the optional "databricks" extra.
    from databricks import sql as databricks_sql
except ImportError:  # pragma: no cover - exercised only without the extra installed
    databricks_sql = None

try:  # databricks-sdk ships alongside it, and is only needed for OAuth M2M.
    from databricks.sdk.core import Config, oauth_service_principal
except ImportError:  # pragma: no cover - exercised only without the extra installed
    Config = None
    oauth_service_principal = None

logger = logging.getLogger(__name__)

EXTRA = "databricks"


def normalise_host(host: str) -> str:
    """Return the bare workspace hostname, with any scheme or trailing slash removed."""
    return host.replace("https://", "").replace("http://", "").rstrip("/")


def build_credentials_provider(host: str, client_id: str, client_secret: str):
    """Build an OAuth machine-to-machine credentials provider for a service principal."""
    def credentials_provider():
        """Return a fresh service-principal token provider for the driver."""
        # Checked here rather than when the provider is built, so describing a connection
        # never needs the SDK - only actually opening one does.
        require(Config, EXTRA, "Databricks OAuth (client_id/client_secret) authentication")
        return oauth_service_principal(
            Config(host=f"https://{host}", client_id=client_id, client_secret=client_secret)
        )

    return credentials_provider


def build_connect_kwargs(profile: dict[str, Any]) -> dict[str, Any]:
    """Translate a dbt-databricks profile into databricks.sql.connect() arguments."""
    host = profile.get("host")
    http_path = profile.get("http_path")
    if not host:
        raise ValueError("No 'host' specified for the Databricks target in profiles.yml")
    if not http_path:
        raise ValueError("No 'http_path' specified for the Databricks target in profiles.yml")

    host = normalise_host(host)
    kwargs: dict[str, Any] = {
        "server_hostname": host,
        "http_path": http_path,
        "catalog": pick(profile, "catalog", "database"),
        "schema": profile.get("schema"),
    }

    token = profile.get("token")
    client_id = profile.get("client_id")
    client_secret = profile.get("client_secret")
    if token:
        kwargs["access_token"] = token
    elif client_id and client_secret:
        kwargs["credentials_provider"] = build_credentials_provider(host, client_id, client_secret)
    else:
        raise ValueError(
            "No Databricks credentials found in profiles.yml: expected either 'token' or "
            "both 'client_id' and 'client_secret'."
        )

    return {key: value for key, value in kwargs.items() if value is not None}


def databricks_client(args: Namespace) -> DbapiClient:
    """Create a Databricks SQL warehouse client using the credentials from the dbt profile."""
    profile = get_profile(args)
    if profile.get("type") != "databricks":
        raise ValueError(f"Target profile type is '{profile.get('type')}', not 'databricks'.")

    connector = require(databricks_sql, EXTRA, "The Databricks connector")
    kwargs = build_connect_kwargs(profile)

    return DbapiClient(
        connect=lambda: connector.connect(**kwargs),
        name="Databricks",
    )
