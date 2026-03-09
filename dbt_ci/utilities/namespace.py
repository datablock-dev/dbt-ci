"""Utility function to convert kwargs dict to argparse.Namespace for easier access and compatibility with existing code"""
import logging
from argparse import Namespace
from typing import Literal, cast
from dbt_ci.cache import CacheManager
from dbt_ci.schema import DbtCiManifest

logger = logging.getLogger(__name__)

def to_namespace(kwargs, command=None):
    """Convert kwargs dict to argparse.Namespace for easier access and compatibility with existing code"""
    if command:
        kwargs["command"] = command
    
    return Namespace(**kwargs)

def get_target(args: Namespace, target: Literal["target", "reference_target"]) -> str | None:
    """Get the target from the Namespace, checking both 'target' and 'reference_target' keys."""
    cache = CacheManager(args)
    cache_manifest = cast(DbtCiManifest, cache.get_cache())
    
    cache_target = cache_manifest.get("config", {}).get(target, {}).get("target", None)
    return getattr(args, target, cache_target)

def get_vars(args: Namespace, target: Literal["vars", "reference_vars"]) -> dict | None:
    """Get the vars from the Namespace, checking both 'vars' and 'reference_vars' keys."""
    cache = CacheManager(args)
    cache_manifest = cast(DbtCiManifest, cache.get_cache())
    
    cache_vars = cache_manifest.get("config", {}).get(target, {}).get("vars", None)
    return getattr(args, target, cache_vars)