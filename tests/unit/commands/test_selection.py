"""Tests for narrowing a run with --select and --exclude."""

import subprocess
from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest

from dbt_ci.commands.run.run import run_nodes
from dbt_ci.commands.run.selection import UserSelection, list_unique_ids, resolve_user_selection
from dbt_ci.graph.parser import generate_dependency_graph


def _graph() -> dict:
    """Parse a manifest with seed s -> model a -> model b, a test on a, one on a and b."""

    def node(name, resource_type="model", parents=()):
        """Build a manifest node entry."""
        return {
            "name": name,
            "resource_type": resource_type,
            "fqn": ["demo", name],
            "original_file_path": f"models/{name}.sql",
            "config": {},
            "columns": {},
            "depends_on": {"macros": ["macro.dbt.test_not_null"], "nodes": list(parents)},
        }

    nodes = {
        "seed.demo.s": node("s", "seed"),
        "model.demo.a": node("a", parents=["seed.demo.s"]),
        "model.demo.b": node("b", parents=["model.demo.a"]),
        "test.demo.t_a": node("t_a", "test", parents=["model.demo.a"]),
        "test.demo.t_ab": node("t_ab", "test", parents=["model.demo.a", "model.demo.b"]),
    }
    parent_map = {node_id: entry["depends_on"]["nodes"] for node_id, entry in nodes.items()}
    child_map = {n: [c for c, ps in parent_map.items() if n in ps] for n in nodes}
    return generate_dependency_graph(
        {
            "metadata": {},
            "nodes": nodes,
            "macros": {},
            "sources": {},
            "parent_map": parent_map,
            "child_map": child_map,
        }
    )


ALL = ["seed.demo.s", "model.demo.a", "model.demo.b", "test.demo.t_a", "test.demo.t_ab"]


class TestUserSelection:
    """Test which picked nodes stay in the run."""

    def test_exclude_drops_matches_and_tests_of_only_excluded_nodes(self):
        """A test goes when everything it tests is excluded, not when one parent is."""
        kept, left_out = UserSelection(excluded={"model.demo.a"}).split(ALL, _graph())
        assert left_out == ["model.demo.a", "test.demo.t_a"]
        assert "test.demo.t_ab" in kept

    def test_select_keeps_matches_and_tests_of_them(self):
        """Tests of selected nodes stay, even when the test itself doesn't match."""
        kept, _ = UserSelection(selected={"model.demo.b"}).split(ALL, _graph())
        assert kept == ["model.demo.b", "test.demo.t_ab"]

    def test_exclude_wins_over_select(self):
        """A node both selected and excluded is left out."""
        selection = UserSelection(selected={"model.demo.a"}, excluded={"model.demo.a"})
        assert not selection.keeps("model.demo.a", _graph())


def _ls(stdout: str):
    """A dbt ls result printing the given lines."""
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


class TestResolveUserSelection:
    """Test resolving selectors with dbt ls."""

    def test_nothing_set(self):
        """Without --select or --exclude nothing is resolved."""
        assert resolve_user_selection(Namespace(select=(), exclude=None)) is None

    def test_selectors_resolved_with_dbt_ls(self):
        """Each option becomes one dbt ls; log lines in its output are ignored."""
        outputs = iter(
            [
                _ls('Running with dbt\n{"unique_id": "model.demo.a"}\n'),
                _ls('{"unique_id": "model.demo.b"}\n'),
            ]
        )
        calls = []

        def fake_run(command_args, runner_config):
            calls.append(command_args)
            return next(outputs)

        args = Namespace(
            select=("tag:x",), exclude=("model.demo.b",), runner="local", dry_run=True, defer=True
        )
        with patch("dbt_ci.commands.run.selection.run_dbt_command", side_effect=fake_run):
            selection = resolve_user_selection(args)
        assert selection == UserSelection(selected={"model.demo.a"}, excluded={"model.demo.b"})
        assert calls[0][:3] == ["ls", "--select", "tag:x"]
        assert "--defer" not in calls[0]

    def test_runs_in_a_dry_run_too(self):
        """dbt ls only reads the project, so a dry run still resolves selectors."""
        seen = {}

        def fake_run(command_args, runner_config):
            seen["dry_run"] = runner_config["dry_run"]
            return _ls("")

        with patch("dbt_ci.commands.run.selection.run_dbt_command", side_effect=fake_run):
            list_unique_ids(["tag:x"], Namespace(runner="local", dry_run=True))
        assert seen["dry_run"] is False


class TestRunNodesWithSelection:
    """Test that run leaves out what the selection drops, and says so."""

    def test_excluded_model_is_not_built(self, caplog):
        """The model step skips the excluded model and logs it."""
        graph = MagicMock()
        graph.to_dict.return_value = _graph()
        executed = []
        with (
            caplog.at_level("INFO"),
            patch(
                "dbt_ci.commands.run.run.run_dbt_command",
                side_effect=lambda command_args, runner_config: executed.append(command_args),
            ),
            patch(
                "dbt_ci.commands.run.run.resolve_dbt_commands", side_effect=lambda cmd, _args: cmd
            ),
        ):
            run_nodes(
                Namespace(nodes="models", dry_run=False, downstream_depth=None, filters=None),
                graph,
                ["model.demo.a"],
                {"modified_nodes": ["model.demo.a"]},
                user_selection=UserSelection(excluded={"model.demo.b"}),
            )
        assert len(executed) == 1
        assert "demo.b" not in executed[0][2] and "demo.a" in executed[0][2]
        assert "Leaving out of the run step by --select/--exclude (1): b" in caplog.text


@pytest.mark.parametrize("option", ["select", "exclude"])
def test_options_from_the_config_file(tmp_path, monkeypatch, option):
    """run.select and run.exclude in the config file reach the run command."""
    import os

    from click.testing import CliRunner

    from dbt_ci.main import cli

    (tmp_path / "dbt-ci.config.yaml").write_text(
        f"run:\n  {option}:\n    - tag:a\n    - tag:b\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    for key in list(os.environ):
        if key.startswith("DBT_"):
            monkeypatch.delenv(key, raising=False)
    captured = {}
    with patch("dbt_ci.commands.run.cli.run", side_effect=lambda args: captured.update(a=args)):
        result = CliRunner().invoke(cli, ["run"])
    assert result.exit_code in (0, None), result.output
    assert list(getattr(captured["a"], option)) == ["tag:a", "tag:b"]
