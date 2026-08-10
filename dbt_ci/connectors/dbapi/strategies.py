"""Delete and migration strategies shared by every DBAPI-based native connector."""
from __future__ import annotations

import logging
from argparse import Namespace
from typing import Callable, cast

from dbt_ci.connectors.dbapi.client import DbapiClient
from dbt_ci.connectors.generic.sql import render_delete_statements
from dbt_ci.schema import DeleteMapNode, MigrationMap, MigrationMapNodeEntry
from dbt_ci.utilities.paths import get_profile

logger = logging.getLogger(__name__)

# Builds the client for one adapter from the dbt profile.
ClientFactory = Callable[[Namespace], DbapiClient]
# Renders the ordered statements that migrate one model to its new physical layout.
# Returning an empty list means "nothing to do for this node".
MigrationPlanner = Callable[[MigrationMapNodeEntry, str], list[str]]


def get_threads(args: Namespace) -> int:
    """Return the thread count dbt is configured with for this target."""
    profile = get_profile(args)
    return cast(int, profile.get("threads", 5) or 5)


def get_adapter_type(args: Namespace) -> str:
    """Return the dbt adapter type configured for the selected target."""
    return cast(str, get_profile(args).get("type", ""))


def log_planned_statements(statements: list[str]) -> None:
    """Report the statements a dry run would have executed."""
    logger.info("Dry run mode enabled - the following statements would be executed:")
    for statement in statements:
        logger.info(f"  • {statement}")


def build_delete_strategy(client_factory: ClientFactory) -> Callable[[dict[str, DeleteMapNode], Namespace], None]:
    """Build a delete strategy that drops removed relations over a DBAPI connection."""
    def delete_strategy(delete_map: dict[str, DeleteMapNode], args: Namespace) -> None:
        """Drop every relation in the delete map, running the drops concurrently."""
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
            log_planned_statements(statements)
            return

        client = client_factory(args)
        try:
            client.execute_batch(statements, threads=get_threads(args))
        finally:
            client.close()

    return delete_strategy


def build_noop_migration_strategy(reason: str) -> Callable[[MigrationMap, Namespace], None]:
    """
    Build a migration strategy for adapters that have no physical layout to migrate.

    Reporting the reason and succeeding is more useful in CI than failing the command:
    there genuinely is nothing to apply, so a red pipeline would be misleading.
    """
    def migration_strategy(migration_map: MigrationMap, args: Namespace) -> None:
        """Explain why nothing was applied."""
        logger.info(reason)

    return migration_strategy


def build_migration_strategy(
    client_factory: ClientFactory,
    planner: MigrationPlanner,
) -> Callable[[MigrationMap, Namespace], None]:
    """
    Build a migration strategy from an adapter's migration SQL.

    The planner renders the ordered steps for a single model. Steps for one model run in
    order; different models migrate concurrently.
    """
    def migration_strategy(migration_map: MigrationMap, args: Namespace) -> None:
        """Apply the new physical layout to every model in the migration map."""
        adapter_type = get_adapter_type(args)
        sequences: list[list[str]] = []
        skipped: list[str] = []

        for node_id, node_data in migration_map["nodes"].items():
            steps = planner(node_data, adapter_type)
            if steps:
                sequences.append(steps)
            else:
                skipped.append(node_id)

        if skipped:
            logger.warning(
                f"No migration statements apply to {len(skipped)} model(s); they were skipped: "
                f"{', '.join(skipped)}"
            )

        if not sequences:
            logger.info("No relations to migrate. Exiting migration strategy.")
            return

        if getattr(args, "dry_run", False):
            log_planned_statements([statement for sequence in sequences for statement in sequence])
            return

        client = client_factory(args)
        try:
            client.execute_sequences(sequences, threads=get_threads(args))
        finally:
            client.close()

    return migration_strategy
