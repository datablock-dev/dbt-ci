"""
Drop relations and schemas on any dbt adapter, through `dbt run-operation`.

Warehouses without a native connector (everything except BigQuery today) are cleaned up
with the adapter's own `drop_relation` and `drop_schema`, so dbt-ci needs no warehouse
SDK and the DDL matches what dbt itself would run.

`run-operation` only runs macros that live in a project, and the user's project must not
be modified. dbt-ci therefore writes a small helper project under the user's project
directory (`target/dbt_ci_operations`) that holds its macros and points at the same
profile. Being inside the project directory, it is also inside any Docker volume that
mounts the project, so every runner can reach it.
"""

import json
import logging
import os
import posixpath
from argparse import Namespace
from importlib import resources
from pathlib import Path
from typing import Optional, TypedDict, cast

import yaml

from dbt_ci.runners import resolve_dbt_commands, run_dbt_command
from dbt_ci.schema import RunnerConfig
from dbt_ci.utilities.paths import get_dbt_project_config

logger = logging.getLogger(__name__)

# Relative to the user's dbt project directory. target/ is dbt's own scratch directory.
OPERATIONS_PROJECT_DIR = ("target", "dbt_ci_operations")
MACRO_FILE = "dbt_ci_operations.sql"

# Flags resolve_dbt_commands adds for build-style commands. The helper project has no
# nodes to defer to, so passing the user's state only makes dbt load a manifest it ignores.
STATE_FLAGS_WITH_VALUE = {"--state"}
STATE_SWITCHES = {"--defer", "--no-defer"}


class RelationRef(TypedDict):
    """A relation to drop: database may be None on adapters without databases."""

    database: Optional[str]
    schema: str
    identifier: str


class SchemaRef(TypedDict):
    """A schema (dataset) to drop."""

    database: Optional[str]
    schema: str


def write_operations_project(args: Namespace) -> Path:
    """Write the helper project next to the user's project and return its path."""
    project_dir = Path(getattr(args, "dbt_project_dir", None) or ".")
    profile = get_dbt_project_config(str(project_dir)).get("profile") or "default"

    operations_dir = project_dir.joinpath(*OPERATIONS_PROJECT_DIR)
    (operations_dir / "macros").mkdir(parents=True, exist_ok=True)
    (operations_dir / "dbt_project.yml").write_text(
        yaml.safe_dump(
            {
                "name": "dbt_ci_operations",
                "version": "1.0.0",
                "config-version": 2,
                "profile": profile,
                "macro-paths": ["macros"],
            }
        )
    )
    macro = resources.files("dbt_ci.dbt").joinpath("macros", MACRO_FILE).read_text()
    (operations_dir / "macros" / MACRO_FILE).write_text(macro)
    # Keeps the helper out of git even where target/ is not ignored
    (operations_dir / ".gitignore").write_text("*\n")
    return operations_dir


def operation_command(args: Namespace, macro: str, macro_args: dict) -> list[str]:
    """
    Build the `dbt run-operation` command for a helper macro.

    The paths come from resolve_dbt_commands, so --project-dir is already what the runner
    sees (an absolute host path, or the path inside the Docker container). The helper
    project sits at a fixed place below it.
    """
    resolved = resolve_dbt_commands(
        ["run-operation", macro, "--args", json.dumps(macro_args)],
        args,
    )

    command: list[str] = []
    skip_value = False
    for arg in resolved:
        if skip_value:
            skip_value = False
            continue
        if arg in STATE_FLAGS_WITH_VALUE:
            skip_value = True
            continue
        if arg in STATE_SWITCHES:
            continue
        command.append(arg)

    if "--project-dir" not in command:
        raise RuntimeError(
            "Could not tell where the dbt project is inside the Docker container. Mount it "
            "with --docker-volumes, or set DBT_PROJECT_DIR in --docker-env."
        )
    index = command.index("--project-dir") + 1
    join = posixpath.join if getattr(args, "runner", None) == "docker" else os.path.join
    command[index] = join(command[index], *OPERATIONS_PROJECT_DIR)
    return command


def run_operation(args: Namespace, macro: str, macro_args: dict) -> None:
    """Run a helper macro through the configured runner, raising if it fails."""
    write_operations_project(args)
    command = operation_command(args, macro, macro_args)
    logger.debug(f"Running dbt run-operation with arguments: {command}")
    run_dbt_command(command_args=command, runner_config=cast(RunnerConfig, args.__dict__))


def drop_relations(args: Namespace, relations: list[RelationRef]) -> None:
    """Drop the given relations if they exist, whatever their type."""
    if not relations:
        return
    run_operation(args, "dbt_ci_drop_relations", {"relations": relations})


def drop_schemas(args: Namespace, schemas: list[SchemaRef]) -> None:
    """Drop the given schemas and everything in them."""
    if not schemas:
        return
    run_operation(args, "dbt_ci_drop_schemas", {"schemas": schemas})
