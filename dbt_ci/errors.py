"""
Exceptions dbt-ci raises for failures it reports to the user.

Library code (graph, runners, connectors, utilities and the helpers behind each command)
raises these instead of exiting the process. Only a command's entry point turns an
error into an exit code, so every failure is reported, and recorded in the run report,
the same way.
"""


class DbtCiError(Exception):
    """Base class for failures dbt-ci explains itself, so no traceback is printed for them."""


class ConfigurationError(DbtCiError, ValueError):
    """
    The dbt project, its profile or dbt-ci's own options are missing or invalid.

    Also a ValueError, which is what invalid configuration raised before this hierarchy.
    """


class ManifestError(DbtCiError):
    """A dbt manifest holds something dbt-ci cannot interpret."""


class DbtCommandError(DbtCiError):
    """
    A dbt invocation failed.

    Every runner raises this for a failed command, whether dbt ran in-process, as a
    local binary, in Docker or through a shell script, so callers never inspect return
    codes themselves.
    """

    def __init__(
        self,
        command: list[str],
        returncode: int | None = None,
        stdout: str = "",
        stderr: str = "",
        detail: str | None = None,
    ):
        """Describe the failed command by its dbt subcommand, exit code and any detail."""
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        message = f"dbt {get_subcommand(command)} failed"
        if returncode is not None:
            message += f" with exit code {returncode}"
        if detail:
            message += f": {detail}"
        super().__init__(message)


def get_subcommand(command: list[str]) -> str:
    """Return the dbt subcommand of an invocation, skipping any entrypoint or `dbt` prefix."""
    for arg in command:
        if arg.startswith("-") or arg == "dbt" or "/" in arg:
            continue
        return arg
    return "command"
