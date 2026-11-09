"""
Narrow a run with dbt selectors: `run --select` and `run --exclude`.

The selectors are resolved to unique_ids with `dbt ls`, so they mean exactly what they
mean to dbt (tags, paths, packages, graph operators). They narrow what dbt-ci picked:
--select keeps only the changed nodes (and the nodes built because of them) that also
match, and --exclude drops matching ones. Tests follow the nodes they check: with
--select a test stays when it or a node it tests matches, and with --exclude it goes
when it matches or everything it tests was excluded.
"""

import logging
from argparse import Namespace
from dataclasses import dataclass, field
from typing import cast

from dbt_ci.commands.init.state_modified import parse_ls_unique_ids
from dbt_ci.errors import DbtCiError
from dbt_ci.graph.graph_utils import get_node
from dbt_ci.runners import resolve_dbt_commands, run_dbt_command
from dbt_ci.schema import DependencyGraph, RunnerConfig

logger = logging.getLogger(__name__)

TEST_TYPES = ("test", "unit_test")


@dataclass
class UserSelection:
    """The nodes --select matched (None without it) and the nodes --exclude matched."""

    selected: set[str] | None = None
    excluded: set[str] = field(default_factory=set)

    def keeps(self, node_id: str, graph: DependencyGraph) -> bool:
        """Report whether a node the run picked stays in it."""
        parents = _tested_nodes(graph, node_id) if node_id.split(".")[0] in TEST_TYPES else []
        if node_id in self.excluded:
            return False
        if parents and all(parent in self.excluded for parent in parents):
            return False
        if self.selected is None:
            return True
        return node_id in self.selected or any(parent in self.selected for parent in parents)

    def split(self, node_ids: list[str], graph: DependencyGraph) -> tuple[list[str], list[str]]:
        """Return the nodes that stay and the nodes left out."""
        kept = [node_id for node_id in node_ids if self.keeps(node_id, graph)]
        return kept, [node_id for node_id in node_ids if node_id not in kept]


def resolve_user_selection(args: Namespace) -> UserSelection | None:
    """Resolve --select and --exclude with dbt ls, or return None when neither is set."""
    select = [value for value in (getattr(args, "select", None) or ()) if value]
    exclude = [value for value in (getattr(args, "exclude", None) or ()) if value]
    if not select and not exclude:
        return None
    selection = UserSelection(
        selected=list_unique_ids(select, args) if select else None,
        excluded=list_unique_ids(exclude, args) if exclude else set(),
    )
    if select:
        logger.info(f"--select {' '.join(select)} matches {len(selection.selected or ())} node(s).")
    if exclude:
        logger.info(f"--exclude {' '.join(exclude)} matches {len(selection.excluded)} node(s).")
    return selection


def list_unique_ids(selectors: list[str], args: Namespace) -> set[str]:
    """
    Return the unique_ids dbt selects for the given selectors.

    dbt ls only reads the project, so it runs in a dry run too; otherwise a dry run
    could not show what the selectors leave out.
    """
    ls_args = Namespace(**{**vars(args), "dry_run": False})
    command = resolve_dbt_commands(
        ["ls", "--select", *selectors, "--output", "json", "--output-keys", "unique_id", "--quiet"],
        ls_args,
        ignore_keys=["defer"],
    )
    result = run_dbt_command(command_args=command, runner_config=cast(RunnerConfig, vars(ls_args)))
    if result is None:
        raise DbtCiError(f"dbt ls returned no output for '{' '.join(selectors)}'.")
    return set(parse_ls_unique_ids(result.stdout))


def _tested_nodes(graph: DependencyGraph, node_id: str) -> list[str]:
    """Return the nodes a test checks: its parents other than macros."""
    node = get_node(graph, node_id)
    if node is None:
        return []
    edges = node.get("upstream_dependencies")
    deps = (edges or {}).get("node_dependencies") or set()
    return [dep for dep in deps if not dep.startswith("macro.")]
