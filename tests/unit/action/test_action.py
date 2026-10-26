"""Tests for the GitHub Action entrypoint in action/dbt_ci_action."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dbt_ci_action import workflow
from dbt_ci_action.__main__ import build_env, main, run_steps
from dbt_ci_action.changes import count_changes, write_change_outputs
from dbt_ci_action.commands import Step, parse_commands
from dbt_ci_action.inputs import flags_for, load_inputs


class TestParseCommands:
    """The `commands` input turns into ordered dbt-ci invocations."""

    def test_one_command_per_line(self):
        """Each line is one command, blank lines and comments are ignored."""
        steps = parse_commands("init\n\n# build\nrun --mode models\nreport\n")
        assert steps == [
            Step(("init",)),
            Step(("run",), ("--mode", "models")),
            Step(("report",)),
        ]

    def test_space_separated_list_on_one_line(self):
        """'init run report' is three commands, not init with two arguments."""
        assert [s.command for s in parse_commands("init run report")] == [
            ("init",),
            ("run",),
            ("report",),
        ]

    def test_leading_dbt_ci_is_dropped(self):
        """Lines copied from a shell script still work."""
        assert parse_commands("dbt-ci run")[0] == Step(("run",))

    def test_plain_ephemeral_means_create(self):
        """'ephemeral' gets its implicit subcommand so flags can follow it."""
        assert parse_commands("ephemeral --target ci")[0] == Step(
            ("ephemeral", "create"), ("--target", "ci")
        )
        assert parse_commands("ephemeral destroy")[0] == Step(("ephemeral", "destroy"))

    @pytest.mark.parametrize("text", ["config", "build", "init; rm -rf /"])
    def test_unsupported_commands_are_rejected(self, text):
        """Only dbt-ci's CI commands can be run."""
        with pytest.raises(ValueError, match="Unsupported"):
            parse_commands(text)

    def test_empty_input_is_rejected(self):
        """An empty list would silently do nothing."""
        with pytest.raises(ValueError, match="empty"):
            parse_commands("\n# nothing\n")


class TestFlags:
    """Inputs become flags on the commands that accept them."""

    INPUTS = {
        "project-dir": "dbt",
        "target": "ci",
        "defer": "true",
        "dry-run": "false",
        "state-uri": "gs://bucket/manifest.json",
        "mode": "models",
        "artifacts-uri": "",
        "pr-comment": "true",
    }

    def test_common_and_init_flags(self):
        """init gets the common flags plus its own; empty and false inputs pass nothing."""
        assert flags_for(("init",), self.INPUTS) == [
            "--dbt-project-dir",
            "dbt",
            "--target",
            "ci",
            "--defer",
            "--state-uri",
            "gs://bucket/manifest.json",
        ]

    def test_command_flags_stay_on_their_command(self):
        """--mode belongs to run only, --pr-comment to report only."""
        assert "--mode" in flags_for(("run",), self.INPUTS)
        assert "--mode" not in flags_for(("report",), self.INPUTS)
        assert "--state-uri" not in flags_for(("run",), self.INPUTS)
        assert flags_for(("report",), self.INPUTS)[-1] == "--pr-comment"
        assert "--pr-comment" not in flags_for(("ephemeral", "destroy"), self.INPUTS)

    def test_pr_comment_false_overrides_the_config_file(self):
        """An explicit false is passed on, so it wins over notifications.pr-comment."""
        assert flags_for(("report",), {"pr-comment": "false"}) == ["--no-pr-comment"]

    def test_invalid_boolean_is_rejected(self):
        """A typo in a boolean input fails instead of being read as false."""
        with pytest.raises(ValueError, match="defer"):
            flags_for(("run",), {"defer": "yes please"})

    def test_load_inputs_strips_values(self):
        """The inputs context arrives as JSON; values are stripped strings."""
        assert load_inputs('{"target": " ci\\n", "x": null}') == {"target": "ci"}


class TestBuildEnv:
    """dbt-ci gets a per-job cache directory, the token and the webhook."""

    def test_cache_dir_under_runner_temp_is_exported(self, tmp_path, monkeypatch):
        """The cache lives in RUNNER_TEMP and later steps are told where."""
        github_env = tmp_path / "env"
        monkeypatch.setenv("GITHUB_ENV", str(github_env))
        env = build_env(
            {"github-token": "t", "slack-webhook": "https://hooks"}, {"RUNNER_TEMP": "/rt"}
        )
        assert env["DBT_CI_CACHE_DIR"] == "/rt/dbt-ci"
        assert env["GITHUB_TOKEN"] == "t"
        assert env["DBT_NOTIFICATIONS_WEBHOOK"] == "https://hooks"
        assert github_env.read_text() == "DBT_CI_CACHE_DIR=/rt/dbt-ci\n"

    def test_existing_cache_dir_is_kept(self, monkeypatch):
        """A cache directory the workflow chose is not replaced."""
        monkeypatch.delenv("GITHUB_ENV", raising=False)
        assert build_env({}, {"DBT_CI_CACHE_DIR": "/mine"})["DBT_CI_CACHE_DIR"] == "/mine"


def fake_dbt_ci(tmp_path: Path, failing: str = "") -> str:
    """Write a fake dbt-ci that logs its arguments and fails for one command."""
    script = tmp_path / "dbt-ci"
    log = tmp_path / "calls.log"
    script.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        f"open({str(log)!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n"
        f"sys.exit(1 if sys.argv[1] == {failing!r} else 0)\n"
    )
    script.chmod(0o755)
    return str(script)


class TestRunSteps:
    """Steps run in order, and a failure skips all but the cleanup steps."""

    def test_failure_skips_to_report_and_destroy(self, tmp_path, capsys):
        """After run fails, finalize is skipped but report and ephemeral destroy still run."""
        executable = fake_dbt_ci(tmp_path, failing="run")
        steps = parse_commands("init\nephemeral\nrun\nfinalize\nreport\nephemeral destroy")

        failed = run_steps(executable, steps, {"target": "ci"}, {})

        assert failed == Step(("run",))
        calls = (tmp_path / "calls.log").read_text().splitlines()
        assert calls == [
            "init --target ci",
            "ephemeral create --target ci",
            "run --target ci",
            "report --target ci",
            "ephemeral destroy --target ci",
        ]
        out = capsys.readouterr().out
        assert "::error::'dbt-ci run' failed with exit code 1." in out
        assert "Skipping 'dbt-ci finalize'" in out

    def test_extra_args_follow_input_flags(self, tmp_path):
        """Flags written on the line come last, so they win over the inputs."""
        executable = fake_dbt_ci(tmp_path)
        run_steps(executable, parse_commands("run --mode tests"), {"mode": "models"}, {})
        assert (tmp_path / "calls.log").read_text() == "run --mode models --mode tests\n"


class TestChangeOutputs:
    """The change set from init becomes step outputs."""

    REPORT = {
        "changes": {
            "modified_nodes": {"model": {"a": {}, "b": {}}, "test": {"t": {}}},
            "new_nodes": {},
            "deleted_nodes": None,
        }
    }

    def test_count_changes(self):
        """Nodes are counted across resource types."""
        assert count_changes(self.REPORT) == {"modified": 3, "new": 0, "deleted": 0}
        assert count_changes({"changes": None}) == {"modified": 0, "new": 0, "deleted": 0}

    def test_outputs_are_written(self, tmp_path, monkeypatch):
        """The counts, has-changes and the report path land in GITHUB_OUTPUT."""
        output = tmp_path / "output"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output))
        report_path = tmp_path / "report.json"
        script = tmp_path / "dbt-ci"
        script.write_text(
            f"#!{sys.executable}\n"
            "import json, sys\n"
            "path = sys.argv[sys.argv.index('--output') + 1]\n"
            f"json.dump({self.REPORT!r}, open(path, 'w'))\n"
        )
        script.chmod(0o755)

        write_change_outputs(str(script), [], {}, str(report_path))

        assert output.read_text().splitlines() == [
            "modified=3",
            "new=0",
            "deleted=0",
            "has-changes=true",
            f"report-json={report_path}",
        ]

    def test_no_cache_sets_no_outputs(self, tmp_path, monkeypatch):
        """Without a change set, outputs stay unset and a stale report is not reused."""
        output = tmp_path / "output"
        monkeypatch.setenv("GITHUB_OUTPUT", str(output))
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(self.REPORT))

        assert (
            write_change_outputs(fake_dbt_ci(tmp_path, failing="report"), [], {}, str(report_path))
            is None
        )
        assert not output.exists()
        assert not report_path.exists()


class TestMain:
    """main() wires the pieces together and reports bad inputs clearly."""

    def test_bad_commands_input_exits_2(self, monkeypatch, capsys):
        """An unsupported command fails before anything runs."""
        monkeypatch.setenv("DBT_CI_ACTION_INPUTS", json.dumps({"commands": "build"}))
        assert main() == 2
        assert "::error::Unsupported dbt-ci command 'build'" in capsys.readouterr().out

    def test_failed_step_exits_1(self, tmp_path, monkeypatch):
        """A failing command fails the action."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
        monkeypatch.delenv("GITHUB_ENV", raising=False)
        monkeypatch.delenv("DBT_CI_CACHE_DIR", raising=False)
        monkeypatch.setenv("DBT_CI_EXECUTABLE", fake_dbt_ci(tmp_path, failing="run"))
        monkeypatch.setenv("DBT_CI_ACTION_INPUTS", json.dumps({"commands": "run\nreport"}))
        assert main() == 1


def test_workflow_commands_are_escaped(capsys):
    """Multi-line messages stay inside one annotation."""
    workflow.error("50% done\nnext line")
    assert capsys.readouterr().out == "::error::50%25 done%0Anext line\n"


def test_launcher_runs_from_any_directory(tmp_path):
    """action/run.py finds its package without PYTHONPATH, as the composite step runs it."""
    launcher = Path(__file__).resolve().parents[3] / "action" / "run.py"
    result = subprocess.run(
        [sys.executable, str(launcher)],
        cwd=tmp_path,
        env={"DBT_CI_ACTION_INPUTS": json.dumps({"commands": ""}), "PATH": ""},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "commands' input is empty" in result.stdout
