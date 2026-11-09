import json
import logging
from argparse import Namespace
from typing import TypedDict, cast
from dbt_ci.errors import ConfigurationError
from dbt_ci.graph.dependency_graph import DbtGraph
from dbt_ci.runners import resolve_dbt_commands, run_dbt_command
from dbt_ci.schema import (
    ComparisonStrategy,
    DependencyGraph,
    RunnerConfig,
    StateChangeSummary,
    StateChangeSummaryKeys,
)
from dbt_ci.utilities.git import GitAdapter, GitChangeType
from dbt_ci.commands.init.reasons import (
    ChangeReasons,
    code_differs,
    compare_with_reference,
    drift_reason,
    file_reason,
    macro_reason,
)
from dbt_ci.graph.graph_utils import (
    get_deleted_nodes,
    get_new_nodes,
    get_node,
    get_nodes_from_path,
    get_nodes,
    get_nodes_using_macros,
    get_structured_modified_nodes,
)

logger = logging.getLogger(__name__)


def parse_ls_unique_ids(output: str) -> list[str]:
    """
    Extract unique_ids from `dbt ls --output json --output-keys unique_id`.

    dbt emits one JSON object per line, but runners interleave their own log lines with
    that output, so non-JSON lines are skipped rather than parsed as a whole document.
    """
    unique_ids: list[str] = []
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            logger.debug(f"Ignoring non-JSON line in dbt ls output: {line}")
            continue

        unique_id = entry.get("unique_id")
        if unique_id:
            unique_ids.append(unique_id)

    return unique_ids


def add_macro_users(
    git_modified_nodes: dict[GitChangeType, set[str]],
    target_graph: DependencyGraph,
    reasons: ChangeReasons | None = None,
) -> None:
    """
    Mark every node that uses a changed macro as modified.

    A macro has no downstream edges in the manifest, so selecting the macro itself runs
    nothing; the nodes calling it (directly or via other macros) are what need to rebuild.
    Each user is credited with the macro (or macros) that brought it in.
    """
    changed_macros = sorted(
        node_id
        for node_ids in git_modified_nodes.values()
        for node_id in node_ids
        if node_id.startswith("macro.")
    )
    for macro_id in changed_macros:
        for node_id in get_nodes_using_macros(target_graph, {macro_id}):
            if node_id not in git_modified_nodes["added"]:
                git_modified_nodes["modified"].add(node_id)
            if reasons is not None:
                reasons.add(node_id, macro_reason(macro_id))


def reconcile_with_graphs(
    git_modified_nodes: dict[GitChangeType, set[str]],
    target_graph: DependencyGraph,
    reference_graph: DependencyGraph,
    reasons: ChangeReasons | None = None,
) -> None:
    """
    Re-classify git's file-level changes by whether the node exists in each manifest.

    git reports a moved file as a delete of the old path plus an add of the new one, but
    the node keeps its unique_id. A node still present in the target was not deleted, and
    a node already present in the reference is not new; both are modifications.
    """
    for node_id in list(git_modified_nodes["deleted"]):
        if get_node(target_graph, node_id) is not None:
            git_modified_nodes["deleted"].discard(node_id)
            git_modified_nodes["modified"].add(node_id)
            if reasons is not None:
                reasons.add(node_id, "moved or renamed")
    for node_id in list(git_modified_nodes["added"]):
        if get_node(reference_graph, node_id) is not None:
            git_modified_nodes["added"].discard(node_id)
            git_modified_nodes["modified"].add(node_id)
            if reasons is not None:
                reasons.add(node_id, "moved or renamed")


def empty_change_set() -> dict[GitChangeType, set[str]]:
    """Return an empty set of ids (or paths) per git change type."""
    return {"modified": set(), "added": set(), "deleted": set()}


class CommonStateChangeSummary(TypedDict):
    """The unique_ids dbt's state:modified comparison reports, before any git filtering."""

    modified_node_ids: set[str]
    deleted_node_ids: set[str]
    new_node_ids: set[str]


class StateModified:
    """Resolves the set of modified, new and deleted nodes for the configured strategy."""

    def __init__(self, args: Namespace):
        self.args = args
        self.strategy: ComparisonStrategy = getattr(args, "comparison_strategy")
        self._target_graph: DependencyGraph | None = None
        self._reference_graph: DependencyGraph | None = None
        # Why each node ended up in the change set, filled in by the strategies
        self.reasons = ChangeReasons()

    @property
    def target_graph(self) -> DependencyGraph:
        """
        Return the target dependency graph, parsing the manifest at most once.

        Building a graph re-reads and re-parses the whole manifest, which is expensive on
        large projects. The manifests don't change while a change set is being resolved
        (the reference compile has finished and the target compile hasn't started), so
        the parsed graphs are safe to reuse across strategies.
        """
        if self._target_graph is None:
            self._target_graph = DbtGraph(self.args).to_dict()
        return self._target_graph

    @property
    def reference_graph(self) -> DependencyGraph:
        """Return the reference dependency graph, parsing the manifest at most once."""
        if self._reference_graph is None:
            self._reference_graph = DbtGraph(self.args, is_reference=True).to_dict()
        return self._reference_graph

    def get_state_modified(self) -> StateChangeSummary:
        """Resolve the modified, new and deleted nodes with the configured comparison strategy."""
        if self.strategy == "git":
            return self.git_strategy()
        elif self.strategy == "hybrid":
            return self.hybrid_strategy()
        elif self.strategy == "dbt":
            return self.dbt_strategy()
        raise ConfigurationError(
            f"Invalid comparison strategy '{self.strategy}'. "
            "Supported strategies are 'git', 'dbt' and 'hybrid'."
        )

    def git_strategy(self) -> StateChangeSummary:
        """Determine modified nodes purely from the git diff against the base branch."""
        git = GitAdapter(self.args)
        target_dict = self.target_graph
        reference_dict = self.reference_graph
        changed_files = git.get_changed_files()

        git_modified_nodes = empty_change_set()

        # Get modified nodes based on git diff
        for change_type, files in changed_files.items():
            for file_path in files:
                # One file can define several nodes (a schema.yml declares many
                # tests), so every node at that path is attributed to the change.
                nodes_at_path = get_nodes_from_path(
                    target_dict, file_path, include_patch_path=True
                ) or get_nodes_from_path(reference_dict, file_path, include_patch_path=True)
                if nodes_at_path:
                    for node_info in nodes_at_path:
                        git_modified_nodes[change_type].add(node_info["id"])
                        self.reasons.add(
                            node_info["id"], file_reason(change_type, file_path, node_info)
                        )
                else:
                    logger.debug(
                        f"File {file_path} changed according to git but no corresponding node "
                        "found in either target or reference graph (e.g. a non-dbt file)."
                    )

        add_macro_users(git_modified_nodes, target_dict, self.reasons)
        reconcile_with_graphs(git_modified_nodes, target_dict, reference_dict, self.reasons)

        return {
            "modified_nodes": get_structured_modified_nodes(
                get_nodes(
                    dependency_graph=target_dict, node_ids=list(git_modified_nodes["modified"])
                )
            ),
            "deleted_nodes": get_structured_modified_nodes(
                get_nodes(
                    dependency_graph=reference_dict,
                    node_ids=list(git_modified_nodes["deleted"]),
                )
            ),
            "new_nodes": get_structured_modified_nodes(
                get_nodes(dependency_graph=target_dict, node_ids=list(git_modified_nodes["added"]))
            ),
        }

    def hybrid_strategy(self) -> StateChangeSummary:
        """
        Resolve the change set with dbt's state:modified, kept to the nodes git changed.

        dbt also flags nodes whose environment-specific config differs from production;
        cross-referencing the git diff leaves those out.
        """
        git = GitAdapter(self.args)
        target_graph = self.target_graph
        reference_graph = self.reference_graph
        modified_nodes_dbt = self.common_state_change()
        changed_files = git.get_changed_files()
        new_nodes = get_new_nodes(reference_graph, target_graph)

        git_modified_nodes = empty_change_set()

        unmatched_files = empty_change_set()

        # Get modified nodes based on git diff
        for change_type, files in changed_files.items():
            for file_path in files:
                nodes_at_path = get_nodes_from_path(target_graph, file_path) or get_nodes_from_path(
                    reference_graph, file_path
                )
                if nodes_at_path:
                    for node_info in nodes_at_path:
                        node_id = node_info["id"]
                        self.reasons.add(node_id, file_reason(change_type, file_path, node_info))
                        if new_nodes and node_id in new_nodes:
                            git_modified_nodes["added"].add(node_id)
                        else:
                            git_modified_nodes[change_type].add(node_id)
                # Here we look into the nodes changed according to dbt
                # And see if the changed node in dbt has the same path
                # as the changed file in git. If yes, we consider it truly modified.
                else:
                    unmatched_files[change_type].add(file_path)

        # Structure the nodes from the output of Dbt
        # We want to filter out the nodes that already exists in
        # git_modified_nodes from the dbt modified nodes
        structured_modified_nodes_dbt: StateChangeSummary = {
            "modified_nodes": get_structured_modified_nodes(
                get_nodes(
                    dependency_graph=target_graph,
                    node_ids=list(modified_nodes_dbt["modified_node_ids"]),
                    exclude_node_ids=list(git_modified_nodes["modified"]),
                )
            ),
            "deleted_nodes": get_structured_modified_nodes(
                get_nodes(
                    dependency_graph=reference_graph,
                    node_ids=list(modified_nodes_dbt["deleted_node_ids"]),
                    exclude_node_ids=list(git_modified_nodes["deleted"]),
                )
            ),
            "new_nodes": get_structured_modified_nodes(
                get_nodes(
                    dependency_graph=target_graph,
                    node_ids=list(modified_nodes_dbt["new_node_ids"]),
                    exclude_node_ids=list(git_modified_nodes["added"]),
                )
            ),
        }

        # Now we resolve the ones that are unmatched by looking into
        # the output from dbt state:modified
        # We seek to see what was actually changed. For example, if a schema.yml file
        # has been modified, we want to identify the actual nodes that were changed.
        # A single schema.yml modification can produce new tests, modified tests, or
        # deleted tests — so we search all dbt buckets and classify nodes by where
        # dbt put them, not by the git change type of the file.
        dbt_key_to_git_key: dict[StateChangeSummaryKeys, GitChangeType] = {
            "modified_nodes": "modified",
            "new_nodes": "added",
            "deleted_nodes": "deleted",
        }
        for unmatched_type, unmatched_paths in unmatched_files.items():
            for file_path in list(unmatched_paths):  # copy — we mutate the set inside
                found = False
                for dbt_key, target_git_key in dbt_key_to_git_key.items():
                    # Structured nodes are grouped by resource type: {type: {id: node}}
                    buckets = structured_modified_nodes_dbt.get(dbt_key) or {}
                    dbt_nodes = [item for bucket in buckets.values() for item in bucket.items()]
                    for node_id, dbt_node in dbt_nodes:
                        if dbt_node.get("original_file_path") == file_path:
                            self.reasons.add(
                                node_id, file_reason(unmatched_type, file_path, dbt_node)
                            )
                            if new_nodes and node_id in new_nodes:
                                # New according to dbt, so added, even if git says the
                                # file was modified
                                git_modified_nodes["added"].add(node_id)
                            else:
                                # Use dbt's classification, not the git change type
                                git_modified_nodes[target_git_key].add(node_id)
                            found = True
                            # Don't break — multiple nodes can share one file (schema.yml)
                if found:
                    unmatched_files[unmatched_type].discard(file_path)

        # A model's properties (config, contract, columns) live in its YAML patch file,
        # not in its .sql file. When git changed that YAML and dbt flagged the model,
        # it was really modified even though its own path did not change.
        changed_paths = {file_path for files in changed_files.values() for file_path in files}
        for node_id in modified_nodes_dbt["modified_node_ids"]:
            node = get_node(target_graph, node_id)
            if node is not None and node.get("patch_path") in changed_paths:
                git_modified_nodes["modified"].add(node_id)
                self.reasons.add(node_id, f"properties in `{node.get('patch_path')}` changed")

        add_macro_users(git_modified_nodes, target_graph, self.reasons)
        reconcile_with_graphs(git_modified_nodes, target_graph, reference_graph, self.reasons)

        # Now lets see if there are any unmatched nodes left
        for unmatched_type, unmatched_paths in unmatched_files.items():
            if unmatched_paths:
                logger.debug(
                    f"Unmatched files for change type '{unmatched_type}': {unmatched_paths}"
                )

        # If git produced no hits at all, fall back entirely to dbt's output.
        # This happens when the working tree is clean (e.g. manifest was updated
        # remotely) but dbt state:modified still detects changes.
        if not any(nodes for nodes in git_modified_nodes.values()):
            logger.debug(
                "Git returned no changed files — falling back to dbt state:modified output."
            )
            self.explain_against_reference(structured_modified_nodes_dbt, git)
            return structured_modified_nodes_dbt

        return {
            "modified_nodes": get_structured_modified_nodes(
                get_nodes(
                    dependency_graph=target_graph, node_ids=list(git_modified_nodes["modified"])
                )
            ),
            "deleted_nodes": get_structured_modified_nodes(
                get_nodes(
                    dependency_graph=reference_graph,
                    node_ids=list(git_modified_nodes["deleted"]),
                )
            ),
            "new_nodes": get_structured_modified_nodes(
                get_nodes(dependency_graph=target_graph, node_ids=list(git_modified_nodes["added"]))
            ),
        }

    def dbt_strategy(self) -> StateChangeSummary:
        """Resolve the change set from dbt's state:modified comparison alone."""
        data = self.common_state_change()

        summary: StateChangeSummary = {
            "modified_nodes": get_structured_modified_nodes(
                get_nodes(
                    dependency_graph=self.target_graph, node_ids=list(data["modified_node_ids"])
                )
            ),
            "deleted_nodes": get_structured_modified_nodes(
                get_nodes(
                    dependency_graph=self.reference_graph,
                    node_ids=list(data["deleted_node_ids"]),
                )
            ),
            "new_nodes": get_structured_modified_nodes(
                get_nodes(dependency_graph=self.target_graph, node_ids=list(data["new_node_ids"]))
            ),
        }
        self.explain_against_reference(summary)
        return summary

    def explain_against_reference(
        self, summary: StateChangeSummary, git: GitAdapter | None = None
    ) -> None:
        """
        Record why dbt's state comparison flagged each node, and spot drift.

        dbt says that a node changed, not why, so each version is compared with the
        reference manifest (code checksum, config keys). When git can tell what this
        branch changed, a node whose code differs although the branch never touched its
        file is marked as such: that difference comes from the base branch and the
        reference manifest being out of step, not from this pull request.
        """
        for change_key in ("modified_nodes", "new_nodes", "deleted_nodes"):
            for nodes in (summary.get(change_key) or {}).values():  # type: ignore[attr-defined]
                for node_id in nodes:
                    for reason in compare_with_reference(
                        node_id, change_key, self.reference_graph, self.target_graph
                    ):
                        self.reasons.add(node_id, reason)

        branch_diff = self._branch_changed_paths(git)
        if branch_diff is None:
            return
        changed_paths, base_branch = branch_diff
        for nodes in (summary.get("modified_nodes") or {}).values():
            for node_id, node in nodes.items():
                reference = get_node(self.reference_graph, node_id)
                target = get_node(self.target_graph, node_id)
                if reference is None or target is None or not code_differs(reference, target):
                    continue
                if node.get("original_file_path") not in changed_paths:
                    self.reasons.add(node_id, drift_reason(base_branch))

    def _branch_changed_paths(self, git: GitAdapter | None) -> tuple[set[str], str] | None:
        """
        Return the files this branch changed and its base branch, or None if unknown.

        Only a diff against the merge base says what this branch changed; without one
        (no repository, no remote, history that cannot be found) nothing is claimed.
        """
        try:
            if git is None:
                git = GitAdapter(self.args, best_effort=True)
            if not getattr(git, "merge_base_found", False):
                return None
            changed = {path for paths in git.get_changed_files().values() for path in paths}
            return changed, git.base_branch
        except Exception as e:
            logger.debug(f"Not checking the branch's git diff to explain changes: {e}")
            return None

    def common_state_change(self) -> CommonStateChangeSummary:
        """
        Common logic to determine modified, new, and deleted nodes using
        dbt's state:modified comparison, without git diff filtering.
        This is used by both the dbt_strategy and hybrid_strategy functions
        to avoid code duplication in the initial retrieval of modified nodes from dbt.
        """
        # unique_id rather than name: names are ambiguous across packages and
        # between a model and a singular test, so a bare name cannot identify a node.
        # The reference target and vars go in before resolve_dbt_commands, which then
        # leaves out the current --target/--vars. Appending them afterwards passed each
        # flag twice: dbt v1 silently took the last one, dbt v2 rejects the command.
        ls_command = [
            "ls",
            "--select",
            "state:modified",
            "--output",
            "json",
            "--output-keys",
            "unique_id",
            "--quiet",
        ]
        reference_target = getattr(self.args, "reference_target", None)
        if reference_target:
            ls_command.extend(["--target", reference_target])

        reference_vars = getattr(self.args, "reference_vars", None)
        if reference_vars:
            ls_command.extend(["--vars", reference_vars])

        commands = resolve_dbt_commands(ls_command, self.args)

        logger.debug(f"Running dbt ls command with arguments: {commands}")

        ls_output = run_dbt_command(
            command_args=commands, runner_config=cast(RunnerConfig, self.args.__dict__)
        )

        # Only a dry run skips dbt ls, and it then has no dbt state changes to report
        if ls_output is None:
            logger.info("Dry run: dbt ls was not executed, so no dbt state changes are reported.")
            return {"new_node_ids": set(), "deleted_node_ids": set(), "modified_node_ids": set()}

        modified_nodes = parse_ls_unique_ids(ls_output.stdout)

        new_node_ids = set(get_new_nodes(self.reference_graph, self.target_graph) or [])
        deleted_node_ids = set(get_deleted_nodes(self.reference_graph, self.target_graph) or [])
        truly_modified_nodes = set(
            [n for n in modified_nodes if n not in new_node_ids and n not in deleted_node_ids]
        )

        return {
            "new_node_ids": new_node_ids,
            "deleted_node_ids": deleted_node_ids,
            "modified_node_ids": truly_modified_nodes,
        }
