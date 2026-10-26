"""Every runner reports a failed dbt command the same way: by raising DbtCommandError."""

import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from dbt_ci.errors import ConfigurationError, DbtCommandError
from dbt_ci.runners.bash import bash_runner
from dbt_ci.runners.common import absolutize_path_flags
from dbt_ci.runners.dbt import dbt_runner
from dbt_ci.runners.local import local_runner


def _called_process_error(returncode: int = 2) -> subprocess.CalledProcessError:
    """Build the error subprocess.run(check=True) raises for a failed dbt process."""
    return subprocess.CalledProcessError(
        returncode, ["dbt", "run"], output="1 of 2 ERROR", stderr="Database Error"
    )


class TestSubprocessRunners:
    """The local and bash runners share one subprocess wrapper."""

    @pytest.mark.parametrize(
        "runner, config",
        [
            (local_runner, {"entrypoint": "/venv/bin/dbt"}),
            (bash_runner, {"shell_path": "/bin/bash", "entrypoint": "dbt"}),
        ],
    )
    def test_failed_process_raises_dbt_command_error(self, runner, config):
        """A non-zero exit becomes DbtCommandError carrying dbt's output and exit code."""
        with patch("dbt_ci.runners.common.subprocess.run", side_effect=_called_process_error(2)):
            with pytest.raises(DbtCommandError) as exc_info:
                runner(["run", "--select", "orders"], config)

        error = exc_info.value
        assert str(error) == "dbt run failed with exit code 2"
        assert error.returncode == 2
        assert error.stdout == "1 of 2 ERROR"
        assert error.stderr == "Database Error"

    def test_missing_binary_is_a_configuration_error(self):
        """A dbt executable that does not exist is reported as such, not as a dbt failure."""
        missing = FileNotFoundError(2, "No such file or directory")
        with patch("dbt_ci.runners.common.subprocess.run", side_effect=missing):
            with pytest.raises(ConfigurationError, match="Could not run '/nope/dbt'"):
                local_runner(["ls"], {"entrypoint": "/nope/dbt"})

    def test_success_returns_the_completed_process(self):
        """A successful run hands back the process, whose stdout callers parse."""
        completed = subprocess.CompletedProcess(["dbt", "ls"], 0, stdout="{}", stderr="")
        with patch("dbt_ci.runners.common.subprocess.run", return_value=completed):
            assert local_runner(["ls"], {"entrypoint": "dbt", "quiet": True}) is completed


class TestDbtRunner:
    """The in-process runner raises instead of returning a failing return code."""

    def invoke(self, result: SimpleNamespace):
        """Run dbt_runner against a dbtRunner whose invoke() returns the given result."""
        with patch("dbt_ci.runners.dbt.dbtRunner") as runner_class:
            runner_class.return_value.invoke.return_value = result
            return dbt_runner(["dbt", "build", "--select", "orders"], {})

    def test_failed_nodes_raise(self):
        """dbt reports failed models and tests through success=False, not an exception."""
        with pytest.raises(DbtCommandError, match="dbt build failed with exit code 1"):
            self.invoke(SimpleNamespace(result=None, success=False, exception=None))

    def test_dbt_exception_raises_with_its_message(self):
        """An exception dbt returns (e.g. a project that does not parse) is chained."""
        cause = RuntimeError("Compilation Error in model orders")
        with pytest.raises(DbtCommandError, match="Compilation Error in model orders") as exc_info:
            self.invoke(SimpleNamespace(result=None, success=False, exception=cause))
        assert exc_info.value.__cause__ is cause

    def test_success_returns_stdout(self):
        """A list result (dbt ls) is joined into stdout like a subprocess would print it."""
        result = self.invoke(SimpleNamespace(result=["a", "b"], success=True, exception=None))
        assert result.returncode == 0
        assert result.stdout == "a\nb"


def test_absolutize_path_flags_only_touches_path_values(tmp_path, monkeypatch):
    """Relative path flag values become absolute; everything else is passed through."""
    monkeypatch.chdir(tmp_path)
    command = ["run", "--project-dir", "dbt", "--state", "/abs/state", "--select", "dbt"]
    assert absolutize_path_flags(command) == [
        "run",
        "--project-dir",
        str(tmp_path / "dbt"),
        "--state",
        "/abs/state",
        "--select",
        "dbt",
    ]


def test_docker_image_not_found_is_a_configuration_error(mock_runner_config):
    """A missing image points at --docker-image instead of failing as a dbt error."""
    from docker import errors

    from dbt_ci.runners.docker import docker_runner

    client = MagicMock()
    client.containers.run.side_effect = errors.ImageNotFound("no such image")
    with patch("dbt_ci.runners.docker.docker.client.from_env", return_value=client):
        with pytest.raises(ConfigurationError, match="--docker-image"):
            docker_runner(["dbt", "debug"], mock_runner_config({"docker_image": "dbt:nope"}))
