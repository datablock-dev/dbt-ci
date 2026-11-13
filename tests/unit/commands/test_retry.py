"""Unit tests for retrying a failed run step with dbt retry (--retries)."""

import os
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from dbt_ci.commands.run.retry import get_retries, resolve_retry_command
from dbt_ci.commands.run.run import run_step
from dbt_ci.errors import DbtCommandError

COMMAND = ["run", "--select", "demo.a"]
RETRY = ["retry", "--project-dir", "/p"]


@pytest.fixture(autouse=True)
def no_dbt_state(monkeypatch):
    """Keep a DBT_STATE from the shell or an earlier config load out of these tests."""
    monkeypatch.delenv("DBT_STATE", raising=False)
    monkeypatch.delenv("DBT_TARGET_PATH", raising=False)


def args(**overrides) -> Namespace:
    """Return run's arguments for a local runner deferring to a reference state."""
    values = {
        "runner": "local",
        "dbt_project_dir": "/p",
        "profiles_dir": "/p",
        "reference_state": "/p/.dbtstate",
        "target": "ci",
        "vars": "{x: 1}",
        "defer": True,
        "retries": None,
    }
    return Namespace(**{**values, **overrides})


class TestGetRetries:
    """Test reading --retries."""

    @pytest.mark.parametrize(("value", "expected"), [(None, 0), (0, 0), (2, 2), (-1, 0)])
    def test_values(self, value, expected):
        """Unset or negative never retries."""
        assert get_retries(Namespace(retries=value)) == expected

    def test_missing_option(self):
        """Commands without the option never retry."""
        assert get_retries(Namespace()) == 0


class TestResolveRetryCommand:
    """Test the dbt retry invocation."""

    def test_leaves_out_state_and_defer(self):
        """--state would make dbt retry read run_results.json from the reference state."""
        command = resolve_retry_command(args())
        assert command == [
            "retry",
            "--project-dir",
            "/p",
            "--profiles-dir",
            "/p",
            "--target",
            "ci",
            "--vars",
            "{x: 1}",
        ]

    def test_leaves_out_the_comparison_state(self):
        """init's merge-base baseline is not where dbt retry reads either."""
        assert "--state" not in resolve_retry_command(args(comparison_state="/p/.baseline"))

    def test_points_dbt_state_back_at_the_target_path(self, monkeypatch):
        """A DBT_STATE variable would otherwise redirect dbt retry to the reference state."""
        monkeypatch.setenv("DBT_STATE", "/p/.dbtstate")
        command = resolve_retry_command(args())
        assert command[-2:] == ["--state", str(Path("/p/target").absolute())]

    def test_honours_dbt_target_path(self, monkeypatch):
        """dbt writes run_results.json under DBT_TARGET_PATH when it is set."""
        monkeypatch.setenv("DBT_STATE", "/p/.dbtstate")
        monkeypatch.setenv("DBT_TARGET_PATH", "out")
        assert resolve_retry_command(args())[-1] == str(Path("/p/out").absolute())

    def test_docker_uses_the_container_target_path(self):
        """With DBT_STATE in the container, the target path is a container path too."""
        command = resolve_retry_command(
            args(
                runner="docker",
                dbt_project_dir=os.path.abspath("dbt"),
                profiles_dir=None,
                docker_volumes=[f"{os.path.abspath('dbt')}:/dbt"],
                docker_env=["DBT_STATE=/dbt/.dbtstate"],
            )
        )
        assert command[:3] == ["retry", "--project-dir", "/dbt"]
        assert command[-2:] == ["--state", "/dbt/target"]

    def test_docker_without_dbt_state(self):
        """Without DBT_STATE in the container, no --state is passed."""
        command = resolve_retry_command(
            args(
                runner="docker",
                dbt_project_dir=os.path.abspath("dbt"),
                profiles_dir=None,
                docker_volumes=[f"{os.path.abspath('dbt')}:/dbt"],
            )
        )
        assert "--state" not in command


class TestRunStep:
    """Test running one step with retries."""

    def run(self, outcomes, retries, wrote_results=True):
        """
        Run a step whose dbt commands succeed or fail in turn, and return the commands run.

        wrote_results says whether a failed command wrote its own run_results.json.
        """
        executed = []
        outcomes = iter(outcomes)
        marker = iter(range(100))

        def fake_dbt(command_args, runner_config):
            """Record the command and fail it when its outcome says so."""
            executed.append(command_args[0])
            if not next(outcomes):
                raise DbtCommandError(command_args, returncode=1)

        with (
            patch("dbt_ci.commands.run.run.run_dbt_command", side_effect=fake_dbt),
            patch("dbt_ci.commands.run.run.resolve_retry_command", return_value=RETRY),
            patch(
                "dbt_ci.commands.run.run.run_results_marker",
                side_effect=lambda _args: next(marker) if wrote_results else None,
            ),
            patch("dbt_ci.commands.run.run.record_run_times") as record,
        ):
            run_step(Namespace(retries=retries), list(COMMAND))
        assert record.call_count == len(executed)
        return executed

    def test_success_needs_no_retry(self):
        """A step that passes runs once."""
        assert self.run([True], retries=2) == ["run"]

    def test_failure_without_retries(self):
        """By default a failed step fails the run."""
        with pytest.raises(DbtCommandError):
            self.run([False], retries=None)

    def test_retry_that_succeeds(self):
        """A failed step is rerun with dbt retry, and the step passes once it succeeds."""
        assert self.run([False, True], retries=2) == ["run", "retry"]

    def test_retries_run_out(self):
        """The step fails with the last retry's error."""
        with pytest.raises(DbtCommandError, match="dbt retry failed"):
            self.run([False, False, False], retries=2)

    def test_reruns_the_command_when_dbt_wrote_no_results(self):
        """
        Without results of its own, dbt retry would read the previous step's.

        A step that fails before running any node, say on a connection error, is rerun.
        """
        assert self.run([False, True], retries=1, wrote_results=False) == ["run", "run"]
