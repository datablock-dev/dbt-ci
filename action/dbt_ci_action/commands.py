"""Parse the `commands` input into the dbt-ci invocations the action runs."""
from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import List, Tuple

SUPPORTED_COMMANDS = ("init", "run", "delete", "ephemeral", "migration", "report", "finalize")
EPHEMERAL_SUBCOMMANDS = ("create", "destroy")

# Steps that still run after an earlier one failed: the report explains the failure, and
# tearing down the ephemeral environment must not be skipped because `run` broke.
ALWAYS_RUN: Tuple[Tuple[str, ...], ...] = (("report",), ("ephemeral", "destroy"))


@dataclass(frozen=True)
class Step:
    """One dbt-ci invocation: the command words and any extra arguments given for it."""

    command: Tuple[str, ...]
    args: Tuple[str, ...] = ()

    @property
    def always_run(self) -> bool:
        """Whether the step runs even after an earlier step failed."""
        return self.command in ALWAYS_RUN

    @property
    def label(self) -> str:
        """Human-readable form of the invocation, e.g. 'run --mode models'."""
        return shlex.join([*self.command, *self.args])


def parse_line(line: str) -> List[Step]:
    """Parse one line of the `commands` input into one or more steps."""
    tokens = shlex.split(line, comments=True)
    if tokens and tokens[0] == "dbt-ci":
        tokens = tokens[1:]
    if not tokens:
        return []

    # "init run report" on one line is a list of commands, not init with arguments.
    if len(tokens) > 1 and all(token in SUPPORTED_COMMANDS for token in tokens):
        return [step for token in tokens for step in parse_line(token)]

    name, rest = tokens[0], tokens[1:]
    if name not in SUPPORTED_COMMANDS:
        raise ValueError(
            f"Unsupported dbt-ci command '{name}' in the 'commands' input. "
            f"Supported commands: {', '.join(SUPPORTED_COMMANDS)}."
        )
    if name == "ephemeral":
        # Plain `ephemeral` means `ephemeral create`; naming it lets flags follow it.
        if rest and rest[0] in EPHEMERAL_SUBCOMMANDS:
            return [Step(("ephemeral", rest[0]), tuple(rest[1:]))]
        return [Step(("ephemeral", "create"), tuple(rest))]
    return [Step((name,), tuple(rest))]


def parse_commands(text: str) -> List[Step]:
    """Parse the newline-separated `commands` input into an ordered list of steps."""
    steps = [step for line in text.splitlines() for step in parse_line(line)]
    if not steps:
        raise ValueError("The 'commands' input is empty; list at least one dbt-ci command.")
    return steps
