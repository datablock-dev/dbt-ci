"""Redshift client construction from a dbt profile."""
from __future__ import annotations

import logging
from argparse import Namespace
from typing import Any

from dbt_ci.connectors.dbapi.client import DbapiClient, pick
from dbt_ci.utilities.optional_imports import require
from dbt_ci.utilities.paths import get_profile

try:  # redshift-connector ships in the optional "redshift" extra.
    import redshift_connector
except ImportError:  # pragma: no cover - exercised only without the extra installed
    redshift_connector = None

logger = logging.getLogger(__name__)

EXTRA = "redshift"

# dbt-redshift's 'method' selects how credentials are obtained.
IAM_METHODS = {"iam", "iam_role"}


def build_connect_kwargs(profile: dict[str, Any]) -> dict[str, Any]:
    """Translate a dbt-redshift profile into redshift_connector.connect() arguments."""
    database = pick(profile, "dbname", "database")
    if not database:
        raise ValueError("No 'dbname' specified for the Redshift target in profiles.yml")

    kwargs: dict[str, Any] = {
        "host": profile.get("host"),
        "database": database,
        "port": profile.get("port", 5439),
        "user": pick(profile, "user", "username"),
        "timeout": profile.get("connect_timeout"),
        "sslmode": profile.get("sslmode"),
    }

    method = (profile.get("method") or "database").lower()
    if method in IAM_METHODS:
        # With IAM the driver fetches temporary credentials itself, so no password is sent.
        kwargs.update({
            "iam": True,
            "db_user": pick(profile, "user", "username"),
            "cluster_identifier": profile.get("cluster_id"),
            "profile": profile.get("iam_profile"),
            "region": profile.get("region"),
            "auto_create": profile.get("autocreate"),
            "db_groups": profile.get("db_groups"),
        })
        # redshift-connector authenticates IAM against the database name, not the user.
        kwargs.pop("user", None)
    else:
        password = profile.get("password")
        if not password:
            raise ValueError(
                "No 'password' specified for the Redshift target in profiles.yml. Set one, "
                "or use method: iam."
            )
        kwargs["password"] = password

    return {key: value for key, value in kwargs.items() if value is not None}


def redshift_client(args: Namespace) -> DbapiClient:
    """Create a Redshift client using the credentials from the dbt profile."""
    profile = get_profile(args)
    if profile.get("type") != "redshift":
        raise ValueError(f"Target profile type is '{profile.get('type')}', not 'redshift'.")

    connector = require(redshift_connector, EXTRA, "The Redshift connector")
    kwargs = build_connect_kwargs(profile)

    return DbapiClient(
        connect=lambda: connector.connect(**kwargs),
        name="Redshift",
    )
