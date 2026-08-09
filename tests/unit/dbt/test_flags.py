"""Unit tests for reusing the run configuration that init recorded."""
from argparse import Namespace
from unittest.mock import MagicMock, patch

from dbt_ci.dbt.flags import apply_cached_config, get_cached_value, get_target, get_vars

CACHED = {
    "config": {
        "target": {"target": "dev", "vars": "{'k': 1}"},
        "reference": {"target": "production", "vars": "{'k': 2}"},
    }
}


def _with_cache(cache_contents):
    """Patch CacheManager so the helpers read a known cache payload."""
    manager = MagicMock()
    manager.get_cache.return_value = cache_contents
    return patch("dbt_ci.dbt.flags.CacheManager", return_value=manager)


class TestGetCachedValue:
    """Test lookups into the cached config block."""

    def test_reads_target_section(self):
        """target/vars come from the target section."""
        with _with_cache(CACHED):
            assert get_cached_value(Namespace(), "target") == "dev"
            assert get_cached_value(Namespace(), "vars") == "{'k': 1}"

    def test_reads_reference_section(self):
        """reference_target/reference_vars come from the reference section."""
        with _with_cache(CACHED):
            assert get_cached_value(Namespace(), "reference_target") == "production"
            assert get_cached_value(Namespace(), "reference_vars") == "{'k': 2}"

    def test_unknown_key(self):
        """A key with no recorded home resolves to None."""
        with _with_cache(CACHED):
            assert get_cached_value(Namespace(), "runner") is None

    def test_missing_cache(self):
        """Without a cache nothing is inherited."""
        with _with_cache(None):
            assert get_cached_value(Namespace(), "target") is None


class TestGetters:
    """Test that an explicit value always beats the cached one."""

    def test_explicit_target_wins(self):
        """A target passed on the command line is not overridden by the cache."""
        with _with_cache(CACHED):
            assert get_target(Namespace(target="staging")) == "staging"

    def test_falls_back_to_cache(self):
        """An unset target is inherited from what init recorded."""
        with _with_cache(CACHED):
            assert get_target(Namespace(target=None)) == "dev"

    def test_vars_fall_back_to_cache(self):
        """Same for vars."""
        with _with_cache(CACHED):
            assert get_vars(Namespace(vars="")) == "{'k': 1}"


class TestApplyCachedConfig:
    """Test the namespace-filling entry point the commands call."""

    def test_fills_unset_values(self):
        """init's target and vars are applied when the command didn't specify them."""
        args = Namespace(target=None, vars="")
        with _with_cache(CACHED):
            apply_cached_config(args)

        assert args.target == "dev"
        assert args.vars == "{'k': 1}"

    def test_preserves_explicit_values(self):
        """Explicitly provided values survive untouched."""
        args = Namespace(target="staging", vars="{'own': true}")
        with _with_cache(CACHED):
            apply_cached_config(args)

        assert args.target == "staging"
        assert args.vars == "{'own': true}"

    def test_no_cache_is_a_noop(self):
        """With no cache the namespace is left exactly as it was."""
        args = Namespace(target=None, vars="")
        with _with_cache(None):
            apply_cached_config(args)

        assert args.target is None
        assert args.vars == ""
