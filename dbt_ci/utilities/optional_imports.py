"""Helpers for dependencies that ship as optional extras.

The cloud SDKs and the Docker client are large, and most projects need only one of
them, so they are installed via extras rather than as hard requirements. Modules import
them defensively and call require() at the point of use, which turns a missing extra
into an actionable message instead of an ImportError traceback at startup.
"""
from typing import Any

EXTRA_INSTALL_HINT = "pip install 'dbt-ci[{extra}]'"


def require(dependency: Any, extra: str, purpose: str) -> Any:
    """
    Return an optional dependency, or raise explaining which extra provides it.

    Args:
        dependency: The imported module, or None if the import failed.
        extra: The name of the extra that installs it (e.g. "gcp").
        purpose: What the caller was trying to do, used in the error message.
    """
    if dependency is None:
        raise ImportError(
            f"{purpose} requires the '{extra}' extra, which is not installed. "
            f"Install it with: {EXTRA_INSTALL_HINT.format(extra=extra)}"
        )
    return dependency
