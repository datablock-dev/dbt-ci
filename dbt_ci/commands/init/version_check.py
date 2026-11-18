"""
Warn when the state was built by a different dbt version than the one comparing against it.

dbt's `state:modified` compares node checksums and configs as each dbt version writes
them. When production's manifest comes from another dbt version, nodes can differ only
in how they are serialised, and dbt flags them as modified even though nothing changed:
dbt-core 1.12.7 fixed one such case, where list and dict configs were stringified
(https://github.com/dbt-labs/dbt-core/issues/16133). The result is a much bigger build
than the pull request warrants, with no hint why, so init says so.
"""

import logging
from typing import Any

from dbt_ci.utilities.paths import get_reference_manifest_file

logger = logging.getLogger(__name__)

# Strategies whose change set relies on dbt's own state comparison
STATE_COMPARISON_STRATEGIES = {"dbt", "hybrid"}


def manifest_dbt_version(manifest: Any) -> str | None:
    """Return the dbt version recorded in a manifest's metadata, or None when absent."""
    metadata = manifest.get("metadata") if isinstance(manifest, dict) else None
    version = metadata.get("dbt_version") if isinstance(metadata, dict) else None
    return (str(version).strip() or None) if version else None


def read_state_dbt_version(state_dir: str | None) -> str | None:
    """Return the dbt version that built the manifest in a state directory, if readable."""
    if not state_dir:
        return None
    try:
        return manifest_dbt_version(get_reference_manifest_file(state_dir))
    except (OSError, ValueError) as e:
        logger.debug(f"Could not read the dbt version of the state at '{state_dir}': {e}")
        return None


def version_mismatch_message(state_version: str, current_version: str, strategy: str) -> str:
    """Return the warning shown when the state and this run use different dbt versions."""
    message = (
        f"The state manifest was built with dbt {state_version}, but this run uses dbt "
        f"{current_version}."
    )
    if strategy in STATE_COMPARISON_STRATEGIES:
        message += (
            " dbt's state:modified can flag unchanged nodes as modified across versions, "
            "so the change set may be larger than this branch's changes. Rebuild the state "
            "with the same dbt version, or use --comparison-strategy git."
        )
    return message


def check_state_dbt_version(
    state_dir: str | None, current_manifest: Any, strategy: str
) -> dict[str, str] | None:
    """
    Compare the dbt versions of the state and the current manifest, and warn on a mismatch.

    Returns both versions when they differ, for the report, else None. Missing or
    unreadable versions are not a mismatch: there is nothing to tell the user.
    """
    state_version = read_state_dbt_version(state_dir)
    current_version = manifest_dbt_version(current_manifest)
    if not state_version or not current_version or state_version == current_version:
        return None
    if strategy in STATE_COMPARISON_STRATEGIES:
        logger.warning(version_mismatch_message(state_version, current_version, strategy))
    else:
        logger.info(version_mismatch_message(state_version, current_version, strategy))
    return {"state": state_version, "current": current_version}
