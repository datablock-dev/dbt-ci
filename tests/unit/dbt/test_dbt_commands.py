"""Unit tests for the compile passes init runs against the reference and actual targets."""

from argparse import Namespace
from unittest.mock import patch

import pytest

from dbt_ci.dbt.dbt_commands import DbtCommands
from dbt_ci.errors import ConfigurationError, DbtCommandError


def make_args(**overrides) -> Namespace:
    """Arguments for a local run with a reference target that differs from the target."""
    defaults = {
        "runner": "local",
        "dbt_project_dir": "dbt",
        "profiles_dir": None,
        "reference_state": None,
        "target": "ci",
        "vars": "{run_vars: 1}",
        "reference_target": "production",
        "reference_vars": "{prod_vars: 1}",
        "skip_reference_compile": False,
        "target_compile": True,
        "defer": False,
    }
    return Namespace(**{**defaults, **overrides})


def compiled(args: Namespace, compile_pass: str) -> list[str] | None:
    """Run one compile pass and return the dbt arguments it ran, or None if it ran nothing."""
    with patch("dbt_ci.dbt.dbt_commands.run_dbt_command") as run:
        getattr(DbtCommands(args), compile_pass)()
    return run.call_args.kwargs["command_args"] if run.called else None


def flag_value(command: list[str], flag: str) -> str | None:
    """Return the value passed for a flag, which must appear at most once."""
    assert command.count(flag) <= 1, f"{flag} passed twice: {command}"
    return command[command.index(flag) + 1] if flag in command else None


class TestReferenceCompile:
    """The reference pass compiles against the reference target and vars only."""

    def test_uses_the_reference_target_and_vars(self):
        """The current --target and --vars must not leak into the reference compile."""
        command = compiled(make_args(), "reference_compile")
        assert command[0] == "compile"
        assert flag_value(command, "--target") == "production"
        assert flag_value(command, "--vars") == "{prod_vars: 1}"

    def test_without_a_reference_target(self):
        """With no reference target, dbt's default target is compiled."""
        command = compiled(
            make_args(reference_target=None, reference_vars=None), "reference_compile"
        )
        assert flag_value(command, "--target") is None
        assert flag_value(command, "--vars") is None

    def test_can_be_skipped(self):
        """--skip-reference-compile runs nothing."""
        assert compiled(make_args(skip_reference_compile=True), "reference_compile") is None

    def test_failure_propagates(self):
        """A failed compile fails init instead of being logged and ignored."""
        failure = DbtCommandError(["compile"], returncode=2)
        with patch("dbt_ci.dbt.dbt_commands.run_dbt_command", side_effect=failure):
            with pytest.raises(DbtCommandError):
                DbtCommands(make_args()).reference_compile()


class TestTargetCompile:
    """The second pass compiles the actual target, and only when it differs."""

    def test_compiles_the_actual_target(self):
        """With --target-compile and a different reference target, the target is compiled."""
        command = compiled(make_args(), "target_compile")
        assert flag_value(command, "--target") == "ci"
        assert flag_value(command, "--vars") == "{run_vars: 1}"

    def test_is_opt_in(self):
        """Without --target-compile nothing runs."""
        assert compiled(make_args(target_compile=False), "target_compile") is None

    @pytest.mark.parametrize("reference_target", [None, "ci"])
    def test_same_target_is_not_compiled_twice(self, reference_target):
        """The reference pass already compiled this target."""
        assert compiled(make_args(reference_target=reference_target), "target_compile") is None

    def test_needs_a_project_dir(self):
        """Without a project directory there is nothing to compile."""
        with pytest.raises(ConfigurationError, match="dbt_project_dir"):
            DbtCommands(make_args(dbt_project_dir=None)).target_compile()
