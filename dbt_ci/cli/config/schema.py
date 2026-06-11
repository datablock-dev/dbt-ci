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
    "defer":         {"aliases": ["DBT_DEFER"], "type": "bool"},
    "dry-run":       {"aliases": ["dry_run", "DBT_DRY_RUN"], "type": "bool"},
    "log-level":     {"aliases": ["log_level", "DBT_LOG_LEVEL"], "type": "enum", "choices": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]},
    "quiet":         {"aliases": ["DBT_QUIET"], "type": "bool"},
    "slack-webhook": {"aliases": ["slack_webhook", "SLACK_WEBHOOK"], "type": "str"},
    "shell-path":    {"aliases": ["shell_path", "DBT_SHELL_PATH"], "type": "str"},
    "docker": {
        "type": "section",
        "fields": {
            "image":    {"type": "str"},
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
}


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
    elif kind == "enum":
        choices = rule["choices"]
        normalized = value.upper() if isinstance(value, str) else value
        if normalized not in choices:
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
    for k in set(raw.keys()) - _valid_keys(SCHEMA):
        errors.append(f"Unknown key '{k}'")
    for k, v in raw.items():
        rule = _find_rule(k, SCHEMA)
        if rule:
            _validate_value(k, v, rule, errors)
    return errors
