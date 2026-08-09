"""Execution of SQL against any warehouse through ``dbt run-operation``."""
from __future__ import annotations

import json
import logging
from argparse import Namespace
from subprocess import CompletedProcess
from typing import Any, cast

from dbt_ci.runners import resolve_dbt_commands, run_dbt_command
from dbt_ci.schema import RunnerConfig

logger = logging.getLogger(__name__)

# `run_query` is part of dbt's global project, so it is callable in every dbt project
# without dbt-ci having to install a macro into the user's repository.
RUN_QUERY_MACRO = "run_query"

# A run-operation selects no nodes, so state comparison and deferral have nothing to act
# on. Both are dropped from the invocation: they add no value, and older dbt versions
# reject them on this command.
UNUSED_RUN_OPERATION_KEYS = ["reference_state", "defer"]


def run_operation(
    args: Namespace,
    macro: str,
    macro_args: dict[str, Any] | None = None,
) -> CompletedProcess | None:
    """Invoke ``dbt run-operation`` for a macro through the configured runner."""
    command = ["run-operation", macro]
    if macro_args is not None:
        # JSON is valid YAML, so it parses as dbt's --args mapping while staying safe for
        # values containing quotes. Runners pass argv lists, so no shell quoting is involved.
        command.extend(["--args", json.dumps(macro_args)])

    return run_dbt_command(
        command_args=resolve_dbt_commands(command, args, ignore_keys=UNUSED_RUN_OPERATION_KEYS),
        runner_config=cast(RunnerConfig, args.__dict__),
    )


def execute_statements(args: Namespace, statements: list[str]) -> None:
    """
    Execute SQL statements one at a time through dbt's ``run_query`` macro.

    Statements are issued sequentially rather than in parallel: each one starts a separate
    dbt invocation, and most warehouses reject multiple statements in a single query.
    """
    for index, statement in enumerate(statements, start=1):
        logger.info(f"[{index}/{len(statements)}] {statement}")
        run_operation(args, RUN_QUERY_MACRO, {"sql": statement})
