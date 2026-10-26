"""Tests for the error hierarchy and how failures are reported."""

import logging
import threading
from unittest.mock import patch

import pytest

from dbt_ci.errors import ConfigurationError, DbtCiError, DbtCommandError, ManifestError
from dbt_ci.graph.parser import generate_dependency_graph
from dbt_ci.utilities.logging import print_exception
from dbt_ci.utilities.multi_threading import run_multithreaded


class TestDbtCommandError:
    """The message names the dbt subcommand, not the binary or wrapper that ran it."""

    @pytest.mark.parametrize(
        "command",
        [
            ["run", "--select", "orders"],
            ["dbt", "run", "--select", "orders"],
            ["/venv/bin/dbt", "run"],
            ["--quiet", "run"],
        ],
    )
    def test_names_the_subcommand(self, command):
        """Prefixes such as 'dbt', a binary path or global flags are skipped."""
        assert str(DbtCommandError(command, returncode=1)) == "dbt run failed with exit code 1"

    def test_detail_without_exit_code(self):
        """An in-process failure has no exit code, only dbt's own message."""
        assert str(DbtCommandError(["ls"], detail="boom")) == "dbt ls failed: boom"

    def test_is_a_dbt_ci_error(self):
        """Every error dbt-ci reports itself shares one base class."""
        for error_class in (ConfigurationError, ManifestError, DbtCommandError):
            assert issubclass(error_class, DbtCiError)

    def test_configuration_error_is_a_value_error(self):
        """Callers that caught ValueError for bad configuration keep working."""
        assert issubclass(ConfigurationError, ValueError)


class TestPrintException:
    """Errors dbt-ci explains itself are reported without a source location."""

    def raise_and_print(self, error: Exception, caplog) -> str:
        """Raise the error so it has a traceback, print it, and return the error log."""
        try:
            raise error
        except Exception as e:
            with caplog.at_level(logging.ERROR):
                print_exception(e, "Run failed")
        return caplog.text

    def test_dbt_ci_error_has_no_location(self, caplog):
        """The message is the whole story for a DbtCiError."""
        text = self.raise_and_print(DbtCommandError(["run"], returncode=1), caplog)
        assert "Run failed: dbt run failed with exit code 1" in text
        assert "File:" not in text

    def test_unexpected_error_keeps_its_location(self, caplog):
        """A bug still points at the file and line it came from."""
        text = self.raise_and_print(KeyError("boom"), caplog)
        assert "File:" in text and "Line:" in text


class TestRunMultithreaded:
    """Concurrent work returns results in order and fails loudly."""

    def test_results_keep_the_input_order(self):
        """Results line up with the functions, whatever order they finish in."""
        assert run_multithreaded([lambda i=i: i * 2 for i in range(5)], threads=3) == [
            0,
            2,
            4,
            6,
            8,
        ]

    def test_every_function_runs_before_the_first_error_is_raised(self):
        """A failure does not leave the rest of a batch of drops unsubmitted."""
        ran: list[int] = []
        lock = threading.Lock()

        def work(i: int) -> None:
            """Record the call, failing for one of them."""
            with lock:
                ran.append(i)
            if i == 1:
                raise RuntimeError("drop failed")

        with pytest.raises(RuntimeError, match="drop failed"):
            run_multithreaded([lambda i=i: work(i) for i in range(4)], threads=2)
        assert sorted(ran) == [0, 1, 2, 3]


def test_unknown_node_type_in_manifest_raises():
    """A manifest node type dbt-ci cannot map is a ManifestError, not a process exit."""
    manifest = {"child_map": {"model.pkg.a": []}, "nodes": {"model.pkg.a": {"name": "a"}}}
    with patch.dict("dbt_ci.graph.parser.MANIFEST_KEY_MAPPING", {"model": None}):
        with pytest.raises(ManifestError, match="Unknown node type 'model'"):
            generate_dependency_graph(manifest)
