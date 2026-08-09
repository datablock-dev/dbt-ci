"""Delete and migration strategies that work on any dbt adapter."""
from __future__ import annotations

import logging
from argparse import Namespace
from typing import cast

from dbt_ci.connectors.generic.run_operation import execute_statements
from dbt_ci.connectors.generic.sql import render_delete_statements, render_drop_statement
from dbt_ci.runners import resolve_dbt_commands, run_dbt_command
from dbt_ci.schema import DeleteMapNode, MigrationMap, RunnerConfig
from dbt_ci.utilities.paths import get_profile

logger = logging.getLogger(__name__)


def get_adapter_type(args: Namespace) -> str:
    """Return the dbt adapter type configured for the selected target."""
    return cast(str, get_profile(args).get("type", ""))


def generic_delete_strategy(delete_map: dict[str, DeleteMapNode], args: Namespace) -> None:
    """Drop removed models by issuing DDL through ``dbt run-operation``."""
    adapter_type = get_adapter_type(args)
    statements: list[str] = []

    for node_metadata in delete_map.values():
        table_id = node_metadata.get("table_id")
        if not table_id:
            continue
        statements.extend(
            render_delete_statements(
                table_id=table_id,
                materialization=node_metadata.get("materialization"),
                adapter_type=adapter_type,
            )
        )

    if not statements:
        logger.info("No relations to drop. Exiting delete strategy.")
        return

    if getattr(args, "dry_run", False):
        logger.info("Dry run mode enabled - the following statements would be executed:")
        for statement in statements:
            logger.info(f"  • {statement}")
        return

    logger.info(f"Dropping {len(statements)} relation(s) via dbt run-operation...")
    execute_statements(args, statements)


def generic_migration_strategy(migration_map: MigrationMap, args: Namespace) -> None:
    """
    Rebuild models whose physical layout config changed, on any dbt adapter.

    The relation is dropped through ``dbt run-operation`` and then rebuilt by dbt with
    ``--full-refresh``, which lets the adapter emit its own DDL for the new layout. Unlike
    the BigQuery strategy this does not copy the existing rows across: the model is rebuilt
    from its sources, so history that only exists in the target table is not preserved.
    """
    adapter_type = get_adapter_type(args)
    nodes = migration_map["nodes"]

    statements: list[str] = []
    model_names: list[str] = []
    for node_id, node_data in nodes.items():
        table_id = node_data.get("table_id")
        if not table_id:
            continue
        statements.append(
            render_drop_statement(
                table_id=table_id,
                materialization=node_data.get("materialization"),
                adapter_type=adapter_type,
            )
        )
        model_names.append(node_data.get("name") or node_id.split(".")[-1])

    if not statements:
        logger.info("No relations to rebuild. Exiting migration strategy.")
        return

    if getattr(args, "dry_run", False):
        logger.info("Dry run mode enabled - the following statements would be executed:")
        for statement in statements:
            logger.info(f"  • {statement}")
        logger.info(f"  • dbt run --full-refresh --select {' '.join(model_names)}")
        return

    logger.warning(
        f"Rebuilding {len(model_names)} model(s) from source with --full-refresh. Rows that "
        "only exist in the target relation will not survive the rebuild."
    )
    execute_statements(args, statements)
    full_refresh_models(args, model_names)


def full_refresh_models(args: Namespace, model_names: list[str]) -> None:
    """Rebuild the given models with ``dbt run --full-refresh``."""
    logger.info(f"Rebuilding models with dbt: {', '.join(model_names)}")
    run_dbt_command(
        command_args=resolve_dbt_commands(
            ["run", "--full-refresh", "--select", " ".join(model_names)],
            args,
        ),
        runner_config=cast(RunnerConfig, args.__dict__),
    )
