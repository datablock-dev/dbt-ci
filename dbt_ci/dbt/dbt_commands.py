"""This module contains utility functions for DBT commands, such as compiling the reference state."""

import logging
from argparse import Namespace
from typing import cast
from dbt_ci.errors import ConfigurationError
from dbt_ci.schema import RunnerConfig
from dbt_ci.runners import resolve_dbt_commands, run_dbt_command

logger = logging.getLogger(__name__)


class DbtCommands:
    """Utility class for DBT commands."""

    def __init__(self, args: Namespace):
        """Keep the resolved arguments for the compile passes."""
        self.args = args
        self.dbt_project_dir = getattr(args, "dbt_project_dir", None)

    def reference_compile(self) -> None:
        """Compile the reference DBT project to generate the manifest.json."""
        if getattr(self.args, "skip_reference_compile", False):
            logger.info("Skipping reference compilation as per configuration.")
            return

        # init runs this first; the reference target (usually production) decides what
        # the manifest compiles against, so the comparison with the state is like for like.
        command = ["compile"]
        reference_target = getattr(self.args, "reference_target", None)
        reference_vars = getattr(self.args, "reference_vars", None)
        if reference_target is None:
            logger.warning(
                "No reference target specified, using current target as reference state for comparison."
            )
        else:
            command.extend(["--target", reference_target])
            if reference_vars:
                command.extend(["--vars", reference_vars])

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

        logger.info("DBT project compiled successfully. manifest.json generated.")

    def target_compile(self) -> None:
        """Compile the target DBT project to generate the manifest.json."""
        target_command = ["compile"]
        target = getattr(self.args, "target", None)
        reference_target = getattr(self.args, "reference_target", None)
        is_reference_target_same_as_current = (
            reference_target is None or reference_target == getattr(self.args, "target", None)
        )

        # Compiling against the actual target is opt-in, through --target-compile
        if not getattr(self.args, "target_compile", False):
            return

        logger.info("Compiling towards target to generate manifest.json for target state.")

        if self.dbt_project_dir is None:
            raise ConfigurationError("dbt_project_dir argument is required for target compilation.")

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
