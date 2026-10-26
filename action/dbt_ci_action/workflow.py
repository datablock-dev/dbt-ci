"""GitHub Actions workflow commands: log groups, annotations, step outputs and job env."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import Iterator


def _escape(message: str) -> str:
    """Escape a message so a workflow command keeps it on one line."""
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _command(name: str, message: str) -> None:
    """Print a workflow command such as ::error::."""
    sys.stdout.write(f"::{name}::{_escape(message)}\n")
    sys.stdout.flush()


def error(message: str) -> None:
    """Annotate the run with an error."""
    _command("error", message)


def warning(message: str) -> None:
    """Annotate the run with a warning."""
    _command("warning", message)


def notice(message: str) -> None:
    """Annotate the run with a notice."""
    _command("notice", message)


@contextmanager
def group(title: str) -> Iterator[None]:
    """Fold everything printed inside the block into a collapsible log group."""
    _command("group", title)
    try:
        yield
    finally:
        _command("endgroup", "")


def _append(file_variable: str, name: str, value: str) -> None:
    """Append a NAME=value line to the file a GITHUB_* variable points at, if set."""
    path = os.environ.get(file_variable)
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{name}={value}\n")


def set_output(name: str, value: str) -> None:
    """Set a step output."""
    _append("GITHUB_OUTPUT", name, value)


def export_env(name: str, value: str) -> None:
    """Export an environment variable to the later steps of the job."""
    _append("GITHUB_ENV", name, value)
