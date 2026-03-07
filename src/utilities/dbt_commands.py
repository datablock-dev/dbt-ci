"""This module contains utility functions for DBT commands, such as compiling the reference state."""
import sys
import logging
from argparse import Namespace
from typing import Any, cast
from src.cache import CacheManager
from src.logging import print_exception
from src.runners import resolve_dbt_commands, run_dbt_command
from src.schema import RunnerConfig
from src.utilities.paths import get_manifest_file, get_profile

logger = logging.getLogger(__name__)

def reference_compile(args: Namespace) -> None:
    """Compile the reference DBT project to generate the manifest.json."""
    try:
        command = ["compile"]

        if getattr(args, "skip_reference_compile", False) is True:
            logger.info("Skipping reference compilation as per configuration.")
            return

        # This function can be called separately if users want to compile towards reference state independently, but by default it will be called during init if a different reference target is specified.
        reference_target = getattr(args, "reference_target", None)
        reference_vars = getattr(args, "reference_vars", None)
        if reference_target is None:
            logger.warning("No reference target specified, using current target as reference state for comparison.")
        else:
            command.extend(["--target", reference_target])
            command.extend(["--vars", reference_vars]) if reference_vars else None

        run_dbt_command(
            command_args=resolve_dbt_commands(
                command_args=command, 
                args=args, 
                ignore_keys=["vars", "target"] # Don't pass vars or target when compiling reference manifest
            ),
            runner_config=RunnerConfig(args.__dict__)
        )

        logger.info("DBT project compiled successfully. manifest.json generated.")
    except Exception:
        logger.error("Error during reference compilation", exc_info=True)
        sys.exit(1)

def target_compile(args: Namespace, store_cache: bool = True) -> None:
    """Compile the target DBT project to generate the manifest.json."""
    try:
        cache = CacheManager()
        dbt_project_dir = getattr(args, "dbt_project_dir", None)
        target_command = ["compile"]
        target = getattr(args, "target", None)
        reference_target = getattr(args, "reference_target", None)
        is_reference_target_same_as_current = reference_target is None or reference_target == getattr(args, "target", None)

        if dbt_project_dir is None:
            logger.error("dbt_project_dir argument is required for target compilation.")
            sys.exit(1)

        if getattr(args, "skip_target_compile", False) is True:
            logger.info("Skipping target compilation as per configuration.")
            return
        
        if is_reference_target_same_as_current:
            logger.info("Reference target is the same as current target, skipping separate compilation for target state.")
            return

        if target and target != "default":
            target_command.extend(["--target", target])

        run_dbt_command(
            command_args=resolve_dbt_commands(target_command, args),
            runner_config=RunnerConfig(args.__dict__)
        )

        if store_cache:
            target_manifest_file = get_manifest_file(dbt_project_dir)
            cache.write_cache(cast(dict[str, Any], target_manifest_file), "target_manifest.json")

    except Exception:
        logger.error("Error during target compilation", exc_info=True)
        sys.exit(1)

def clone_command(
    selected_nodes: list[str],
    args: Namespace
) -> None:
    """Helper function to run the dbt command that will create the ephemeral models based on the selected nodes."""
    try:
        profile = get_profile(args)
        threads = profile.get("threads", 5)

        command = resolve_dbt_commands(
            command_args=["clone", "--select", *selected_nodes, "--threads", str(threads)],
            args=args
        )

        run_dbt_command(
            command_args=command,
            runner_config=RunnerConfig(args.__dict__)
        )
    except Exception as e:
        logger.error(f"Error running dbt clone command: {str(e)}")
        print_exception(e)
        sys.exit(1)