import sys
import logging
from argparse import Namespace
from typing import TypedDict, cast
from dbt_ci.utilities.cache import CacheManager
from dbt_ci.graph.dependency_graph import DbtGraph
from dbt_ci.utilities.logging import print_exception
from dbt_ci.runners import resolve_dbt_commands, run_dbt_command
from dbt_ci.schema import (
    ComparisonStrategy,
    DependencyGraph,
    RunnerConfig,
    StateChangeSummary,
    StateChangeSummaryKeys,
)
from dbt_ci.utilities.git import GitAdapter, GitChangeType
from dbt_ci.graph.graph_utils import (
    get_deleted_nodes,
    get_new_nodes,
    get_node_from_path,
    get_nodes,
    get_structured_modified_nodes
)

logger = logging.getLogger(__name__)

class CommonStateChangeSummary(TypedDict):
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
        """Determines the modified, new, and deleted nodes compared to the reference state based on the specified comparison strategy."""
        if self.strategy == "git":
            return self.git_strategy()
        elif self.strategy == "hybrid":
            return self.hybrid_strategy()
        elif self.strategy == "dbt":
            return self.dbt_strategy()
        else:
            logger.error(f"Invalid comparison strategy specified: {self.strategy}. Supported strategies are 'git', 'dbt', and 'hybrid'.")
            sys.exit(1)

    def git_strategy(self) -> StateChangeSummary:
        """Determine modified nodes purely from the git diff against the base branch."""
        try:
            git = GitAdapter(self.args)
            target_dict = self.target_graph
            reference_dict = self.reference_graph
            changed_files = git.get_changed_files()

            git_modified_nodes = {
                "modified": set(),
                "added": set(),
                "deleted": set()
            }

            # Get modified nodes based on git diff
            for change_type, files in changed_files.items():
                for file_path in files:
                    node_info = get_node_from_path(target_dict, file_path) or get_node_from_path(reference_dict, file_path)
                    if node_info:
                        node_id = node_info.get("name")
                        if node_id:
                            git_modified_nodes[change_type].add(node_id)
                    else:
                        logger.debug(f"File {file_path} changed according to git but no corresponding node found in either target or reference graph (e.g. macro, schema YAML, or non-dbt file).")

            return {
                "modified_nodes": get_structured_modified_nodes(get_nodes(
                    dependency_graph=target_dict, 
                    node_ids=list(git_modified_nodes["modified"])
                )),
                "deleted_nodes": get_structured_modified_nodes(get_nodes(
                    dependency_graph=reference_dict, 
                    node_ids=list(git_modified_nodes["deleted"])
                )),
                "new_nodes": get_structured_modified_nodes(get_nodes(
                    dependency_graph=target_dict, 
                    node_ids=list(git_modified_nodes["added"])
                ))
            }
        except Exception as e:
            print_exception(e, "Error generating state change summary using git strategy")
            sys.exit(1)

    def hybrid_strategy(self) -> StateChangeSummary:
        """Determines modified nodes using dbt state:modified and then cross-references with git diff to filter out nodes that are not actually modified based on file changes."""
        try:
            git = GitAdapter(self.args)
            target_graph = self.target_graph
            reference_graph = self.reference_graph
            modified_nodes_dbt = self.common_state_change()
            changed_files = git.get_changed_files()
            new_nodes = get_new_nodes(reference_graph, target_graph)

            git_modified_nodes = {
                "modified": set(),
                "added": set(),
                "deleted": set()
            }

            unmatched_nodes = {
                "modified": set(),
                "added": set(),
                "deleted": set()
            }

            # Get modified nodes based on git diff
            for change_type, files in changed_files.items():
                for file_path in files:
                    node_info = get_node_from_path(target_graph, file_path) or get_node_from_path(reference_graph, file_path)
                    if node_info:
                        node_id = node_info.get("name")
                        if node_id:
                            if new_nodes and node_id in new_nodes:
                                git_modified_nodes["added"].add(node_id)
                            else:
                                git_modified_nodes[change_type].add(node_id)
                    # Here we look into the nodes changed according to dbt
                    # And see if the changed node in dbt has the same path
                    # as the changed file in git. If yes, we consider it truly modified.
                    else:
                        unmatched_nodes[change_type].add(file_path)

            # Structure the nodes from the output of Dbt
            # We want to filter out the nodes that already exists in 
            # git_modified_nodes from the dbt modified nodes
            structured_modified_nodes_dbt: StateChangeSummary = {
                "modified_nodes": get_structured_modified_nodes(get_nodes(
                    dependency_graph=target_graph, 
                    node_ids=list(modified_nodes_dbt["modified_node_ids"]),
                    exclude_node_ids=list(git_modified_nodes["modified"])
                )),
                "deleted_nodes": get_structured_modified_nodes(get_nodes(
                    dependency_graph=reference_graph, 
                    node_ids=list(modified_nodes_dbt["deleted_node_ids"]),
                    exclude_node_ids=list(git_modified_nodes["deleted"])
                )),
                "new_nodes": get_structured_modified_nodes(get_nodes(
                    dependency_graph=target_graph, 
                    node_ids=list(modified_nodes_dbt["new_node_ids"]),
                    exclude_node_ids=list(git_modified_nodes["added"])
                ))
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
            for change_type, files in unmatched_nodes.items():
                for file_path in list(files):  # copy — we mutate the set inside
                    found = False
                    for dbt_key, target_git_key in dbt_key_to_git_key.items():
                        current_data = structured_modified_nodes_dbt.get(dbt_key) or {}
                        for node_id, node_info in current_data.items():
                            if node_info.get("original_file_path") == file_path:
                                if new_nodes and node_id in new_nodes:
                                    # If the node is new according to dbt, we classify it as added, even if the file was modified according to git
                                    git_modified_nodes["added"].add(node_id)
                                else:
                                    # Use dbt's classification, not the git change type
                                    git_modified_nodes[target_git_key].add(node_id)
                                found = True
                                # Don't break — multiple nodes can share one file (schema.yml)
                    if found:
                        unmatched_nodes[change_type].discard(file_path)

            # Now lets see if there are any unmatched nodes left
            for change_type, files in unmatched_nodes.items():
                if len(files) > 0:
                    logger.debug(f"Unmatched files for change type '{change_type}': {files}")

            # If git produced no hits at all, fall back entirely to dbt's output.
            # This happens when the working tree is clean (e.g. manifest was updated
            # remotely) but dbt state:modified still detects changes.
            if not any(nodes for nodes in git_modified_nodes.values()):
                logger.debug("Git returned no changed files — falling back to dbt state:modified output.")
                return structured_modified_nodes_dbt

            return {
                "modified_nodes": get_structured_modified_nodes(get_nodes(
                    dependency_graph=target_graph, 
                    node_ids=list(git_modified_nodes["modified"])
                )),
                "deleted_nodes": get_structured_modified_nodes(get_nodes(
                    dependency_graph=reference_graph, 
                    node_ids=list(git_modified_nodes["deleted"])
                )),
                "new_nodes": get_structured_modified_nodes(get_nodes(
                    dependency_graph=target_graph, 
                    node_ids=list(git_modified_nodes["added"])
                ))
            }
        except Exception as e:
            print_exception(e, "Error generating state change summary using hybrid strategy")
            sys.exit(1)

    def dbt_strategy(self) -> StateChangeSummary:
        """Compile the DBT project and return a list of modified nodes compared to the reference state."""
        try:
            data = self.common_state_change()

            return {
                "modified_nodes": get_structured_modified_nodes(get_nodes(
                    dependency_graph=self.target_graph,
                    node_ids=list(data["modified_node_ids"])
                )),
                "deleted_nodes": get_structured_modified_nodes(get_nodes(
                    dependency_graph=self.reference_graph,
                    node_ids=list(data["deleted_node_ids"])
                )),
                "new_nodes": get_structured_modified_nodes(get_nodes(
                    dependency_graph=self.target_graph,
                    node_ids=list(data["new_node_ids"])
                ))
            }
        except Exception as e:
            raise Exception(f"Error generating state change summary: {str(e)}")

    def common_state_change(self) -> CommonStateChangeSummary:
        """
            Common logic to determine modified, new, and deleted nodes using 
            dbt's state:modified comparison, without git diff filtering. 
            This is used by both the dbt_strategy and hybrid_strategy functions 
            to avoid code duplication in the initial retrieval of modified nodes from dbt.
        """
        try:
            cache = CacheManager(self.args)

            commands = resolve_dbt_commands(["ls", "--select", "state:modified", "--output", "name", "--quiet"], self.args)
            commands.extend(["--target", getattr(self.args, "reference_target")])
            commands.extend(["--vars", getattr(self.args, "reference_vars")]) if getattr(self.args, "reference_vars", None) else None
    
            logger.debug(f"Running dbt ls command with arguments: {commands}")
    
            ls_output = run_dbt_command(
                command_args=commands,
                runner_config=cast(RunnerConfig, self.args.__dict__)
            )
    
            if ls_output is None:
                logger.info("No modified nodes found during initialization. Exiting...")
                cache.write_cache()
                sys.exit(0)
    
            modified_nodes = ls_output.stdout.splitlines()

            new_node_ids = set(get_new_nodes(self.reference_graph, self.target_graph) or [])
            deleted_node_ids = set(get_deleted_nodes(self.reference_graph, self.target_graph) or [])
            truly_modified_nodes = set([n for n in modified_nodes if n not in new_node_ids and n not in deleted_node_ids])
    
            return {
                "new_node_ids": new_node_ids,
                "deleted_node_ids": deleted_node_ids,
                "modified_node_ids": truly_modified_nodes
            }
        except Exception as e:
            print_exception(e, "Error generating state change summary")
            sys.exit(1)

    def convert_git_key_to_state_change_summary_key(self, key: GitChangeType) -> StateChangeSummaryKeys:
        """Convert the output from git strategy to match the structure of StateChangeSummary for consistency across strategies."""
        mapping: dict[GitChangeType, StateChangeSummaryKeys] = {
            "modified": "modified_nodes",
            "added": "new_nodes",
            "deleted": "deleted_nodes"
        }

        if key not in mapping:
            logger.error(f"Invalid git change type: {key}. Expected one of {list(mapping.keys())}.")
            sys.exit(1)

        return mapping[key]