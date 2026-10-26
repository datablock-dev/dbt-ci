"""This module contains utility functions for DBT commands, such as compiling the reference state."""

import sys
import logging
from argparse import Namespace
from typing import cast
from dbt_ci.utilities.cache import CacheManager
from dbt_ci.schema import RunnerConfig
from dbt_ci.runners import resolve_dbt_commands, run_dbt_command
from dbt_ci.utilities.paths import get_manifest_file

logger = logging.getLogger(__name__)


class DbtCommands:
    """Utility class for DBT commands."""

    def __init__(self, args: Namespace):
        self.args = args
        self.cache = CacheManager(args)
        self.dbt_project_dir = getattr(args, "dbt_project_dir", None)

    def reference_compile(self, store_cache: bool = False) -> None:
        """Compile the reference DBT project to generate the manifest.json."""
        try:
            if getattr(self.args, "skip_reference_compile", False):
                logger.info("Skipping reference compilation as per configuration.")
                return

            # This function can be called separately if users want to compile towards reference state independently, but by default it will be called during init if a different reference target is specified.
            command = ["compile"]
            reference_target = getattr(self.args, "reference_target", None)
            reference_vars = getattr(self.args, "reference_vars", None)
            if reference_target is None:
                logger.warning(
                    "No reference target specified, using current target as reference state for comparison."
                )
            else:
                command.extend(["--target", reference_target])
                command.extend(["--vars", reference_vars]) if reference_vars else None

            run_dbt_command(
                runner_config=cast(RunnerConfig, self.args.__dict__),
                command_args=resolve_dbt_commands(
                    command_args=command,
                    args=self.args,
                    ignore_keys=[
                        "vars",
                        "target",
                    ],  # Don't pass vars or target when compiling reference manifest
                ),
            )

            if store_cache:
                target_manifest_file = get_manifest_file(self.dbt_project_dir)
                self.cache.write_target_manifest(target_manifest_file)

            logger.info("DBT project compiled successfully. manifest.json generated.")
        except Exception:
            logger.error("Error during reference compilation", exc_info=True)
            sys.exit(1)

    def target_compile(self, store_cache: bool = False) -> None:
        """Compile the target DBT project to generate the manifest.json."""
        try:
            target_command = ["compile"]
            target = getattr(self.args, "target", None)
            reference_target = getattr(self.args, "reference_target", None)
            is_reference_target_same_as_current = (
                reference_target is None or reference_target == getattr(self.args, "target", None)
            )

            if not getattr(self.args, "target_compile", False):
                # Removed now that skipping target compilation is the default behavior
                # and users have to explicitly opt-in to compile towards target state by setting
                # --target-compile flag to true.
                # logger.info("Skipping target compilation as per configuration.")
                return

            logger.info("Compiling towards target to generate manifest.json for target state.")

            if self.dbt_project_dir is None:
                logger.error("dbt_project_dir argument is required for target compilation.")
                sys.exit(1)

            if is_reference_target_same_as_current:
                logger.info(
                    "Reference target is the same as current target, skipping separate compilation for target state."
                )
                return

            if target and target != "default":
                target_command.extend(["--target", target])

            run_dbt_command(
                command_args=resolve_dbt_commands(target_command, self.args),
                runner_config=cast(RunnerConfig, self.args.__dict__),
            )

            if store_cache:
                target_manifest_file = get_manifest_file(self.dbt_project_dir)
                self.cache.write_target_manifest(target_manifest_file)

        except Exception:
            logger.error("Error during target compilation", exc_info=True)
            sys.exit(1)
