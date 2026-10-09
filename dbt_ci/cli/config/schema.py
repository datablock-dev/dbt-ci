from typing import Any

# ---------------------------------------------------------------------------
# Declarative validation schema for dbt-ci.config.yaml
#
# Each field entry:
#   type     – "str" | "bool" | "enum" | "list_or_str" | "list_of_enum" | "section"
#   aliases  – alternative key names (e.g. hyphens vs underscores, legacy DBT_* vars)
#   choices  – allowed values for "enum" / "list_of_enum"
#   fields   – nested field schema for "section"
# ---------------------------------------------------------------------------
SCHEMA: dict[str, dict] = {
    "project-dir":   {"aliases": ["project_dir", "DBT_PROJECT_DIR"], "type": "str"},
    "profiles-dir":  {"aliases": ["profiles_dir", "DBT_PROFILES_DIR"], "type": "str"},
    "state":         {"aliases": ["DBT_STATE"], "type": "str"},
    "target":        {"aliases": ["DBT_TARGET"], "type": "str"},
    "vars":          {"aliases": ["DBT_VARS"], "type": "str"},
    "runner":        {"aliases": ["DBT_RUNNER"], "type": "enum", "choices": ["dbt", "local", "docker", "bash"]},
    "entrypoint":    {"aliases": ["DBT_ENTRYPOINT"], "type": "str"},
    "adapter":       {"aliases": ["DBT_ADAPTER"], "type": "str"},
    "dbt-version":   {"aliases": ["dbt_version", "DBT_VERSION"], "type": "str"},
    "defer":         {"aliases": ["DBT_DEFER"], "type": "bool"},
    "dry-run":       {"aliases": ["dry_run", "DBT_DRY_RUN"], "type": "bool"},
    "log-level":     {"aliases": ["log_level", "DBT_LOG_LEVEL"], "type": "enum", "choices": ["DEBUG", "INFO", "WARNING", "WARN", "ERROR", "CRITICAL", "NONE"]},
    "quiet":         {"aliases": ["DBT_QUIET"], "type": "bool"},
    "slack-webhook": {"aliases": ["slack_webhook", "SLACK_WEBHOOK"], "type": "str"},
    "shell-path":    {"aliases": ["shell_path", "DBT_SHELL_PATH"], "type": "str"},
    "docker": {
        "type": "section",
        "fields": {
            "image":    {"aliases": ["DBT_DOCKER_IMAGE"], "type": "str"},
            "platform": {"aliases": ["DBT_DOCKER_PLATFORM"], "type": "str"},
            "volumes":  {"aliases": ["DBT_DOCKER_VOLUMES"], "type": "list_or_str"},
            "env":      {"aliases": ["DBT_DOCKER_ENV"], "type": "list_or_str"},
            "network":  {"aliases": ["DBT_DOCKER_NETWORK"], "type": "str"},
            "user":     {"aliases": ["DBT_DOCKER_USER"], "type": "str"},
            "args":     {"aliases": ["DBT_DOCKER_ARGS"], "type": "str"},
        },
    },
    "init": {
        "type": "section",
        "fields": {
            "reference-target":       {"aliases": ["reference_target"], "type": "str"},
            "reference-vars":         {"aliases": ["reference_vars"], "type": "str"},
            "state-uri":              {"aliases": ["state_uri"], "type": "str"},
            "reference-path":         {"aliases": ["reference_path"], "type": "str"},
            "target-compile":         {"aliases": ["target_compile"], "type": "bool"},
            "skip-reference-compile": {"aliases": ["skip_reference_compile"], "type": "bool"},
            "comparison-strategy":    {"aliases": ["comparison_strategy"], "type": "enum", "choices": ["dbt", "git", "hybrid"]},
            "base-ref":               {"aliases": ["base_ref"], "type": "str"},
        },
    },
    "run": {
        "type": "section",
        "fields": {
            "nodes": {"type": "enum", "choices": ["all", "models", "seeds", "snapshots", "tests"]},
            "downstream-depth": {"aliases": ["downstream_depth"], "type": "int"},
        },
    },
    "finalize": {
        "type": "section",
        "fields": {
            "artifacts-uri":   {"aliases": ["artifacts_uri"], "type": "str"},
            "files":           {"type": "list_of_enum", "choices": ["manifest", "cache", "log"]},
            "clean-ephemeral": {"aliases": ["clean_ephemeral"], "type": "bool"},
        },
    },
    "ephemeral": {
        "type": "section",
        "fields": {
            "keep-env": {"aliases": ["keep_env"], "type": "bool"},
        },
    },
    "notifications": {
        "type": "section",
        "fields": {
            "provider": {"aliases": ["DBT_NOTIFICATIONS_PROVIDER"], "type": "enum", "choices": ["slack"]},
            "format":   {"aliases": ["DBT_NOTIFICATIONS_FORMAT"], "type": "enum", "choices": ["default", "compact", "json"]},
            "webhook":  {"aliases": ["DBT_NOTIFICATIONS_WEBHOOK"], "type": "str"},
            "pr-comment": {"aliases": ["pr_comment", "DBT_NOTIFICATIONS_PR_COMMENT"], "type": "bool"},
        },
    },
    "report": {
        "type": "section",
        "fields": {
            "format": {"aliases": ["DBT_REPORT_FORMAT"], "type": "enum", "choices": ["markdown", "json"]},
            "output": {"aliases": ["DBT_REPORT_OUTPUT"], "type": "str"},
        },
    },
}


def _flat_section_aliases(schema: dict[str, dict]) -> dict[str, dict]:
    """
    Return the rules of section fields that may also be written flat at the top level.

    The legacy flat style puts e.g. DBT_DOCKER_IMAGE next to DBT_RUNNER instead of under
    docker:, so every DBT_-prefixed alias of a section field is accepted there as well.
    """
    flat: dict[str, dict] = {}
    for rule in schema.values():
        if rule["type"] != "section":
            continue
        for field_rule in rule["fields"].values():
            for alias in field_rule.get("aliases", []):
                if alias.startswith("DBT_"):
                    flat[alias] = field_rule
    return flat


def _valid_keys(schema: dict[str, dict]) -> set[str]:
    keys: set[str] = set()
    for primary, rule in schema.items():
        keys.add(primary)
        keys.update(rule.get("aliases", []))
    return keys


def _find_rule(key: str, schema: dict[str, dict]) -> dict | None:
    for primary, rule in schema.items():
        if key == primary or key in rule.get("aliases", []):
            return rule
    return None


def _validate_value(path: str, value: Any, rule: dict, errors: list[str]) -> None:
    kind = rule["type"]
    if kind == "str":
        if not isinstance(value, str):
            errors.append(f"'{path}' must be a string, got {value!r}")
    elif kind == "bool":
        if not isinstance(value, bool):
            errors.append(f"'{path}' must be a boolean (true/false), got {value!r}")
    elif kind == "int":
        # bool is a subclass of int, so reject it explicitly.
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append(f"'{path}' must be an integer, got {value!r}")
    elif kind == "enum":
        choices = rule["choices"]
        if isinstance(value, str):
            if value.lower() not in [c.lower() for c in choices]:
                errors.append(f"'{path}' must be one of {choices!r}, got {value!r}")
        elif value not in choices:
            errors.append(f"'{path}' must be one of {choices!r}, got {value!r}")
    elif kind == "list_or_str":
        if not isinstance(value, (list, str)):
            errors.append(f"'{path}' must be a list or string, got {value!r}")
    elif kind == "list_of_enum":
        choices = rule["choices"]
        items = value if isinstance(value, list) else [value]
        for item in items:
            if item not in choices:
                errors.append(f"'{path}' items must be one of {choices!r}, got {item!r}")
    elif kind == "section":
        _validate_section(path, value, rule["fields"], errors)


def _validate_section(path: str, value: Any, schema: dict[str, dict], errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"'{path}' must be a mapping")
        return
    for k in set(value.keys()) - _valid_keys(schema):
        errors.append(f"Unknown key '{path}.{k}'")
    for k, v in value.items():
        rule = _find_rule(k, schema)
        if rule:
            _validate_value(f"{path}.{k}", v, rule, errors)


def validate_config(raw: dict) -> list[str]:
    """Return a list of human-readable validation error messages for the raw config dict."""
    errors: list[str] = []
    flat_aliases = _flat_section_aliases(SCHEMA)
    for k in set(raw.keys()) - _valid_keys(SCHEMA) - set(flat_aliases):
        errors.append(f"Unknown key '{k}'")
    for k, v in raw.items():
        rule = _find_rule(k, SCHEMA) or flat_aliases.get(k)
        if rule:
            _validate_value(k, v, rule, errors)
    return errors
