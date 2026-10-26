"""Resolution of dbt invocation settings that `init` recorded into the cache.

`init` writes the target, vars, state path, runner and comparison strategy it ran
with into cache.json, and the README promises you "specify state once in init, reuse
everywhere". Later commands used to re-read target, vars and state from the CLI, so
they had to be repeated - and a state path init had defaulted was lost entirely. These
helpers close that gap - an explicitly provided value still wins, the cache only fills
in what was left unset.
"""

import logging
from argparse import Namespace
from typing import Any, cast

from dbt_ci.schema import DbtCiManifest
from dbt_ci.utilities.cache import CacheManager

logger = logging.getLogger(__name__)

# Settings recorded by init that later commands can inherit, mapped to where they live
# in the cached config block.
CONFIG_SECTION: dict[str, str] = {
    "target": "target",
    "vars": "target",
    "reference_target": "reference",
    "reference_vars": "reference",
    "reference_state": "reference",
}


def get_cached_config(args: Namespace) -> dict[str, Any]:
    """Return the config block init recorded, or an empty mapping when unavailable."""
    cache_manifest = cast(DbtCiManifest | None, CacheManager(args).get_cache())
    if not cache_manifest:
        return {}
    return cast(dict[str, Any], cache_manifest.get("config") or {})


def get_cached_value(args: Namespace, key: str) -> Any:
    """Look a single recorded setting up out of the cached config block."""
    section_name = CONFIG_SECTION.get(key)
    if section_name is None:
        return None

    section = get_cached_config(args).get(section_name) or {}
    # Within a section the keys are unprefixed: reference_target -> reference.target
    field = key.replace("reference_", "")
    return section.get(field)


def apply_cached_config(args: Namespace) -> Namespace:
    """
    Fill unset target/vars/state on the args namespace from what init recorded.

    Mutates and returns the namespace so it can be applied at the top of a command.
    Only unset values are filled, so a flag passed on the command line still wins.
    The state path matters most: when init defaulted it, a later command that is not
    told it would run `dbt clone` and other deferring commands without --state.
    """
    for key in ("target", "vars", "reference_state"):
        current = getattr(args, key, None)
        if current:
            continue
        cached = get_cached_value(args, key)
        if cached:
            logger.debug(f"Using {key} recorded by init: {cached}")
            setattr(args, key, cached)

    return args
