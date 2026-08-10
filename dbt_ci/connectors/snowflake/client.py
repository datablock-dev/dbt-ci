"""Snowflake client construction from a dbt profile."""
from __future__ import annotations

import logging
from argparse import Namespace
from typing import Any

from dbt_ci.connectors.dbapi.client import DbapiClient, pick
from dbt_ci.utilities.optional_imports import require
from dbt_ci.utilities.paths import get_profile

try:  # snowflake-connector-python ships in the optional "snowflake" extra.
    import snowflake.connector as snowflake_connector
except ImportError:  # pragma: no cover - exercised only without the extra installed
    snowflake_connector = None

try:  # Pulled in by snowflake-connector-python; only needed for key-pair auth.
    from cryptography.hazmat.primitives import serialization
except ImportError:  # pragma: no cover - exercised only without the extra installed
    serialization = None

logger = logging.getLogger(__name__)

EXTRA = "snowflake"


def load_private_key(profile: dict[str, Any]) -> bytes | None:
    """
    Load a key-pair credential from the profile and return it in the DER form the driver wants.

    dbt accepts either an on-disk key (private_key_path) or the PEM itself (private_key),
    optionally encrypted with private_key_passphrase.
    """
    private_key_path = profile.get("private_key_path")
    private_key = profile.get("private_key")
    if not private_key_path and not private_key:
        return None

    pem = private_key
    if private_key_path:
        with open(private_key_path, "rb") as key_file:
            pem = key_file.read()
    if isinstance(pem, str):
        pem = pem.encode("utf-8")

    passphrase = profile.get("private_key_passphrase")
    loaded = require(serialization, EXTRA, "Snowflake key-pair authentication").load_pem_private_key(
        pem,
        password=passphrase.encode("utf-8") if passphrase else None,
    )

    return loaded.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def build_connect_kwargs(profile: dict[str, Any]) -> dict[str, Any]:
    """Translate a dbt-snowflake profile into snowflake.connector.connect() arguments."""
    account = profile.get("account")
    if not account:
        raise ValueError("No 'account' specified for the Snowflake target in profiles.yml")

    kwargs: dict[str, Any] = {
        "account": account,
        "user": profile.get("user"),
        "role": profile.get("role"),
        "warehouse": profile.get("warehouse"),
        "database": pick(profile, "database", "dbname"),
        "schema": pick(profile, "schema", "dbschema"),
        # Applies dbt-ci's own tag so migration DDL is attributable in query history.
        "session_parameters": {"QUERY_TAG": profile.get("query_tag") or "dbt-ci"},
    }

    # Authentication: key pair, then an explicit authenticator (SSO/OAuth), then password.
    private_key = load_private_key(profile)
    authenticator = profile.get("authenticator")
    if private_key is not None:
        kwargs["private_key"] = private_key
    elif authenticator:
        kwargs["authenticator"] = authenticator
        if profile.get("token"):
            kwargs["token"] = profile["token"]
        if authenticator.lower() == "username_password_mfa" and profile.get("password"):
            kwargs["password"] = profile["password"]
    elif profile.get("password"):
        kwargs["password"] = profile["password"]
    else:
        raise ValueError(
            "No Snowflake credentials found in profiles.yml: expected one of 'password', "
            "'private_key'/'private_key_path', or 'authenticator'."
        )

    if profile.get("client_session_keep_alive") is not None:
        kwargs["client_session_keep_alive"] = profile["client_session_keep_alive"]
    if profile.get("connect_timeout") is not None:
        kwargs["login_timeout"] = profile["connect_timeout"]

    return {key: value for key, value in kwargs.items() if value is not None}


def snowflake_client(args: Namespace) -> DbapiClient:
    """Create a Snowflake client using the credentials from the dbt profile."""
    profile = get_profile(args)
    if profile.get("type") != "snowflake":
        raise ValueError(f"Target profile type is '{profile.get('type')}', not 'snowflake'.")

    connector = require(snowflake_connector, EXTRA, "The Snowflake connector")
    kwargs = build_connect_kwargs(profile)

    return DbapiClient(
        connect=lambda: connector.connect(**kwargs),
        name="Snowflake",
    )
