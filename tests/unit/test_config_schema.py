"""Unit tests for dbt_ci.cli.config.schema validation."""
import pytest
from dbt_ci.cli.config.schema import validate_config


class TestEnumValidation:
    """Enum fields accept the correct values and reject invalid ones."""

    def test_runner_lowercase_accepted(self):
        """Lowercase runner values (the normal case) must not produce errors."""
        for value in ("dbt", "local", "docker", "bash"):
            assert validate_config({"runner": value}) == [], f"runner: {value!r} should be valid"

    def test_runner_invalid_value(self):
        """An unsupported runner value produces an error."""
        errors = validate_config({"runner": "kubernetes"})
        assert any("runner" in e for e in errors)

    def test_log_level_uppercase_accepted(self):
        """Uppercase log-level values must not produce errors."""
        for value in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            assert validate_config({"log-level": value}) == [], f"log-level: {value!r} should be valid"

    def test_log_level_lowercase_accepted(self):
        """Lowercase log-level values should also be accepted (case-insensitive)."""
        assert validate_config({"log-level": "info"}) == []

    def test_comparison_strategy_accepted(self):
        """Valid comparison-strategy values pass."""
        for value in ("dbt", "git", "hybrid"):
            assert validate_config({"init": {"comparison-strategy": value}}) == []

    def test_unknown_top_level_key(self):
        """An unknown top-level key produces an error."""
        errors = validate_config({"unknown_key": "value"})
        assert any("unknown_key" in e for e in errors)

    def test_invalid_bool_field(self):
        """A string where a bool is expected produces an error."""
        errors = validate_config({"defer": "yes"})
        assert any("defer" in e for e in errors)

    def test_valid_config_produces_no_errors(self):
        """A well-formed config produces no errors."""
        config = {
            "runner": "docker",
            "log-level": "INFO",
            "defer": False,
            "docker": {
                "image": "my-registry/dbt:latest",
                "volumes": ["dbt:/dbt:rw"],
            },
            "init": {
                "comparison-strategy": "hybrid",
            },
        }
        assert validate_config(config) == []
