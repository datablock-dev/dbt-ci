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

    def test_notifications_section_accepted(self):
        """The notifications section takes a provider, a format and a webhook."""
        config = {"notifications": {
            "provider": "slack", "format": "compact", "webhook": "https://hooks.example/x", "pr-comment": True,
        }}
        assert validate_config(config) == []

    def test_notifications_invalid_values(self):
        """Unsupported providers and formats are rejected."""
        errors = validate_config({"notifications": {"provider": "teams", "format": "xml"}})
        assert any("notifications.provider" in e for e in errors)
        assert any("notifications.format" in e for e in errors)

    def test_pr_comment_must_be_boolean(self):
        """notifications.pr-comment takes true or false."""
        assert any("pr-comment" in e for e in validate_config({"notifications": {"pr-comment": "yes"}}))

    def test_slack_format_is_not_a_top_level_key(self):
        """The layout lives under notifications, not at the top level."""
        assert any("slack-format" in e for e in validate_config({"slack-format": "json"}))

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


class TestSchemaCoverage:
    """Test that every option the code reads from the config file is accepted by both schemas."""

    @pytest.mark.parametrize("config", [
        {"dbt-version": "1.10.13"},
        {"DBT_VERSION": "1.10.13"},
        {"report": {"format": "json", "output": "report.md"}},
        {"run": {"downstream-depth": 2}},
        {"DBT_DOCKER_IMAGE": "img", "DBT_DOCKER_PLATFORM": "linux/amd64"},
    ])
    def test_keys_are_accepted(self, config):
        """These keys used to be rejected as unknown even though the code reads them."""
        assert validate_config(config) == []

    def test_flat_docker_key_type_is_checked(self):
        """Flat legacy docker keys are validated like their nested counterparts."""
        assert validate_config({"DBT_DOCKER_VOLUMES": 3})

    def test_runtime_keys_exist_in_the_json_schema(self):
        """Editor validation (JSON schema) must not reject keys that dbt-ci accepts."""
        import json
        from pathlib import Path
        from dbt_ci.cli.config.schema import SCHEMA, _flat_section_aliases

        json_schema = json.loads(Path(__file__).parents[2].joinpath("dbt-ci.config.schema.json").read_text())
        properties = json_schema["properties"]
        missing = []
        for key, rule in SCHEMA.items():
            names = [key, *rule.get("aliases", [])]
            missing += [name for name in names if name not in properties]
            if rule["type"] == "section":
                section = properties.get(key, {}).get("properties", {})
                for field, field_rule in rule["fields"].items():
                    field_names = [field, *[a for a in field_rule.get("aliases", []) if not a.startswith("DBT_")]]
                    missing += [f"{key}.{name}" for name in field_names if name not in section]
        missing += [name for name in _flat_section_aliases(SCHEMA) if name not in properties]
        assert missing == []


class TestFlattenConfig:
    """Test how nested config keys are turned into DBT_* names."""

    def test_nested_key_written_with_its_full_name(self):
        """docker: {DBT_DOCKER_PLATFORM: x} maps to DBT_DOCKER_PLATFORM, not a doubled prefix."""
        from dbt_ci.cli.config.parser import _flatten_config

        assert _flatten_config({"docker": {"DBT_DOCKER_PLATFORM": "linux/amd64", "image": "img"}}) == {
            "DBT_DOCKER_PLATFORM": "linux/amd64",
            "DBT_DOCKER_IMAGE": "img",
        }
