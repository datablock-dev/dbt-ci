"""
This module contains the implementation of the `init` command for the dbt CI tool.
"""

import sys
import logging
from argparse import Namespace
from typing import cast
import click
from dbt_ci.utilities.logging import print_exception, redact_namespace
from dbt_ci.utilities.cache import CacheManager
from dbt_ci.dbt.dbt_commands import DbtCommands
from dbt_ci.connectors import init_storage_connector
from dbt_ci.commands.init.state_modified import StateModified
from dbt_ci.schema import DependencyGraphNode, StateChangeSummary
from dbt_ci.utilities.paths import get_manifest_file, get_reference_manifest_file
from dbt_ci.commands.init.resolve_manifest import resolve_manifest_file_from_storage

logger = logging.getLogger(__name__)


def init(args: Namespace):
    """
    Initialize the dbt CI tool with necessary configuration and setup.
    This step compiles the DBT project to ensure that we have a generated manifest.json
    required for the tool to work.

    The tool by default compiles the DBT project with production settings but can be overriden.
    The tool generates two manifest.json files:
    1. The reference manifest.json with target equal to the current target
    2. "Production" reference manifest.json with target equal to the production target (if specified and different from current target)
    """
    try:
        # Convert kwargs to Namespace and resolve configuration
        # Variables class handles type conversions (tuples->lists, string->bool, etc.)
        click.secho("DBT CI Initialization", fg="green", bold=True)
        logger.debug(f"Running with the following arguments: {redact_namespace(args)}")
        if getattr(args, "reference_path", "reference") != "reference":
            logger.warning(
                "--reference-path is deprecated and has no effect: the reference compile "
                "writes to dbt's own target path."
            )
        dbt_commands = DbtCommands(args)
        cache = CacheManager(args)
        state_modified = StateModified(args)
        cache.clear_cache()  # Clear cache at the start of init to avoid stale data issues
        cache.start_report("init", args)
        dbt_project_dir = getattr(args, "dbt_project_dir", None)
        reference_target = getattr(args, "reference_target", None)
        reference_state_path: str | None = getattr(args, "reference_state", None)
        resolved_storage = init_storage_connector(getattr(args, "state_uri", None))

        # Exit if dbt_project_dir is not provided
        if dbt_project_dir is None:
            logger.error(
                "No dbt_project_dir specified. Please provide the path to your DBT project using the --dbt-project-dir argument."
            )
            sys.exit(1)

        if resolved_storage is not None:
            local_state_dir = resolve_manifest_file_from_storage(resolved_storage, args)
            # Update reference_state to use the local path where manifest was downloaded
            setattr(args, "reference_state", str(local_state_dir))

            # Reload reference manifest file after downloading from storage
            cache.write_reference_manifest(get_reference_manifest_file(str(local_state_dir)))
        elif reference_state_path:
            # A local --state directory is just as much a baseline as a downloaded one.
            # Caching it is what lets later commands resolve nodes that no longer exist
            # in the target - without it, `delete` cannot look up what it should drop.
            # Best-effort: if the state isn't there, the comparison below raises a
            # clearer error than failing here would.
            try:
                cache.write_reference_manifest(get_reference_manifest_file(reference_state_path))
            except FileNotFoundError:
                logger.debug(f"No reference manifest at '{reference_state_path}' to cache yet.")

        # Compile dbt and generate reference manifest.json file
        dbt_commands.reference_compile()

        target_manifest_file = get_manifest_file(dbt_project_dir)
        state_change_summary = state_modified.get_state_modified()
        cache.write_cache(state_change_summary)

        if reference_target and reference_target != getattr(args, "target", None):
            # Different targets - will compile again later with actual target
            cache.write_target_manifest(target_manifest_file)
        else:
            # Same target, or none specified. The reference *target* (which warehouse to
            # compile against) is independent of the reference *state* (the baseline to
            # compare with), so an already-cached baseline must not be replaced here -
            # doing so discarded the only copy of the deleted nodes' metadata.
            logger.debug("Reference target is the same as current target!")
            cache.write_target_manifest(target_manifest_file)

            if cache.get_cache("reference_manifest.json") is None:
                logger.debug(
                    "No reference state available. Using the target manifest as the reference."
                )
                cache.write_reference_manifest(target_manifest_file)

        # Will generate summary and output it in the logs. It also covers:
        # 1. Migration plan for partitioning changes
        # 2. Ephemeral plan
        init_summary(state_change_summary, args)

        # Deleted-node dependency validation is left to dbt: compiling the project
        # already fails when a ref()/source() points at a node removed in this change set.

        # Compile with the actual target (not reference target)
        # Use the user-specified target, or let dbt use the default from dbt_project.yml
        dbt_commands.target_compile()

        cache.update_report(command="init", status="completed")
        logger.info("Initialization complete. Cache updated with current state(s).")
        logger.info(
            "You can now run `dbt-ci run --mode <mode>` to execute modified models based on the generated state."
        )
    except Exception as e:
        cache = CacheManager(args)
        cache.update_report(command="init", status="failed")
        print_exception(e, "Error during initialization")
        sys.exit(1)


def init_summary(state_change_summary: StateChangeSummary, args: Namespace) -> None:
    """
    The following method will call the following steps to generate a summary of changes,
    but also migration, ephemeral:
    1. Generate summary of modified, deleted, and new nodes with their resource types
    2. Generate migration plan for modified nodes with partitioning changes
    3. Generate ephemeral plan for modified nodes with non-partitioning changes
    """
    logger.info("\n------------------------------------------------------")
    logger.info("State Change Summary:")
    for change_type, values in state_change_summary.items():
        values = cast(dict[str, DependencyGraphNode], values)
        if values is None or len(values) == 0:
            logger.info(f"\n{change_type.replace('_', ' ').title()}: 0")
            continue

        total_count = sum(len(node_dict) for node_dict in values.values())
        logger.info(f"\n{change_type.replace('_', ' ').title()}: {total_count}")
        for node_dict in values.values():
            for node in node_dict.values():
                node = cast(DependencyGraphNode, node)
                logger.info(f"  • {node['name']} [{node['resource_type']}]")
    logger.info("\n------------------------------------------------------")

    slack_webhook = getattr(args, "slack_webhook", None)
    if not slack_webhook or (getattr(args, "notifications_provider", None) or "slack") != "slack":
        return

    try:
        from dbt_ci.notifications.slack import SlackClient
        from dbt_ci.notifications.slack_summary import build_init_summary_message

        blocks, fallback_text = build_init_summary_message(state_change_summary, args)
        SlackClient(args).send_blocks(blocks, fallback_text)
    except Exception as e:
        logger.error(f"Failed to send Slack message: {e}")
