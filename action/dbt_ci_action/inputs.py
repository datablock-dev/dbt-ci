"""Read the action's inputs and turn them into dbt-ci flags.

Inputs are passed as flags rather than environment variables because dbt-ci ranks its
config file above the environment: an input set on the workflow step is deliberate and
should win over dbt-ci.config.yaml, just as a flag typed on the command line does. Empty
inputs pass nothing, so the config file and dbt-ci's defaults still apply.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

Inputs = Dict[str, str]

# Value flags every dbt-ci command except `config` accepts, keyed by action input.
COMMON_VALUE_FLAGS: Dict[str, str] = {
    "project-dir": "--dbt-project-dir",
    "profiles-dir": "--profiles-dir",
    "target": "--target",
    "vars": "--vars",
    "state": "--state",
    "config": "--config",
    "runner": "--runner",
    "log-level": "--log-level",
}

# On/off flags every command accepts. They have no --no- form, so false passes nothing.
COMMON_SWITCHES: Dict[str, str] = {
    "defer": "--defer",
    "dry-run": "--dry-run",
}

# Value flags only one command accepts, keyed by the command's first word.
COMMAND_VALUE_FLAGS: Dict[str, Dict[str, str]] = {
    "init": {
        "state-uri": "--state-uri",
        "reference-target": "--reference-target",
        "comparison-strategy": "--comparison-strategy",
        "base-ref": "--base-ref",
    },
    "run": {
        "mode": "--mode",
        "downstream-depth": "--downstream-depth",
    },
    "finalize": {
        "artifacts-uri": "--artifacts-uri",
    },
}


def load_inputs(raw: Optional[str]) -> Inputs:
    """Parse the JSON-encoded `inputs` context into a dict of stripped strings."""
    data = json.loads(raw or "{}")
    return {key: str(value).strip() for key, value in data.items() if value is not None}


def parse_bool(inputs: Inputs, name: str) -> Optional[bool]:
    """Read a true/false input, returning None when it is empty."""
    value = inputs.get(name, "").lower()
    if not value:
        return None
    if value in ("true", "yes", "1"):
        return True
    if value in ("false", "no", "0"):
        return False
    raise ValueError(f"Input '{name}' must be 'true' or 'false', got '{inputs[name]}'.")


def common_flags(inputs: Inputs) -> List[str]:
    """Return the flags shared by every command."""
    flags: List[str] = []
    for name, flag in COMMON_VALUE_FLAGS.items():
        if inputs.get(name):
            flags.extend([flag, inputs[name]])
    for name, flag in COMMON_SWITCHES.items():
        if parse_bool(inputs, name):
            flags.append(flag)
    return flags


def flags_for(command: Tuple[str, ...], inputs: Inputs) -> List[str]:
    """Return the flags the inputs translate to for one dbt-ci command."""
    flags = common_flags(inputs)
    for name, flag in COMMAND_VALUE_FLAGS.get(command[0], {}).items():
        if inputs.get(name):
            flags.extend([flag, inputs[name]])
    if command[0] == "report":
        pr_comment = parse_bool(inputs, "pr-comment")
        if pr_comment is not None:
            flags.append("--pr-comment" if pr_comment else "--no-pr-comment")
    return flags
