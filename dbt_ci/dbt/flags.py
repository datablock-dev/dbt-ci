"""Resolution of dbt invocation settings that `init` recorded into the cache.

`init` writes the target, vars, runner and comparison strategy it ran with into
cache.json, and the README promises you "specify state once in init, reuse everywhere".
That was only ever true for state paths: every later command re-read target and vars
from the CLI, so they had to be repeated. These helpers close that gap - an explicitly
provided value still wins, the cache only fills in what was left unset.
"""
import logging
from argparse import Namespace
from typing import Any, Literal, cast

from dbt_ci.schema import DbtCiManifest
from dbt_ci.utilities.cache import CacheManager

logger = logging.getLogger(__name__)

# Settings recorded by init that later commands can inherit, mapped to where they live
# in the cached config block.
type CachedTargetKey = Literal["target", "reference_target"]
type CachedVarsKey = Literal["vars", "reference_vars"]

CONFIG_SECTION: dict[str, str] = {
    "target": "target",
    "vars": "target",
    "reference_target": "reference",
    "reference_vars": "reference",
}


def get_cached_config(args: Namespace) -> dict[str, Any]:
    """Return the config block init recorded, or an empty mapping when unavailable."""
    cache_manifest = cast(DbtCiManifest | None, CacheManager(args).get_cache())
    if not cache_manifest:
        return {}
    return cache_manifest.get("config") or {}


def get_cached_value(args: Namespace, key: str) -> Any:
    """Look a single recorded setting up out of the cached config block."""
    section_name = CONFIG_SECTION.get(key)
    if section_name is None:
        return None

    section = get_cached_config(args).get(section_name) or {}
    # Within a section the keys are unprefixed: reference_target -> reference.target
    field = key.replace("reference_", "")
    return section.get(field)


def get_target(args: Namespace, target: CachedTargetKey = "target") -> str | None:
    """Return the dbt target, preferring an explicit value over the cached one."""
    return getattr(args, target, None) or get_cached_value(args, target)


def get_vars(args: Namespace, key: CachedVarsKey = "vars") -> str | None:
    """Return the dbt vars, preferring an explicit value over the cached one."""
    return getattr(args, key, None) or get_cached_value(args, key)


def apply_cached_config(args: Namespace) -> Namespace:
    """
    Fill unset target/vars on the args namespace from what init recorded.

    Mutates and returns the namespace so it can be applied at the top of a command.
    Only unset values are filled, so a flag passed on the command line still wins.
    """
    for key in ("target", "vars"):
        current = getattr(args, key, None)
        if current:
            continue
        cached = get_cached_value(args, key)
        if cached:
            logger.debug(f"Using {key} recorded by init: {cached}")
            setattr(args, key, cached)

    return args
