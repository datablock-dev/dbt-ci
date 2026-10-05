"""Helpers for telling dbt v1 (dbt-core, Python) apart from dbt v2 (the Rust engine).

dbt v2 is distributed on PyPI as `dbt` (or `dbt-oss` for the Apache-2.0 subset) rather
than `dbt-core`, and bundles its adapters, so pinning a version has to pick the right
distribution and skip the separate adapter install.
"""
from typing import Literal

type DbtDistribution = Literal["dbt-core", "dbt"]

# The first major version shipped as the Rust engine instead of dbt-core.
DBT_V2_MAJOR = 2


def get_major_version(version: str | None) -> int | None:
    """Return the major component of a dbt version string, or None when it can't be parsed."""
    if not version:
        return None
    head = version.strip().lstrip("vV=").split(".", 1)[0]
    return int(head) if head.isdigit() else None


def is_dbt_v2(version: str | None) -> bool:
    """Whether the given version string refers to dbt v2 or later."""
    major = get_major_version(version)
    return major is not None and major >= DBT_V2_MAJOR


def get_dbt_distribution(version: str | None) -> DbtDistribution:
    """Return the PyPI distribution that provides the requested dbt version."""
    return "dbt" if is_dbt_v2(version) else "dbt-core"
