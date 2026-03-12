import sys
import logging
from argparse import Namespace, ArgumentParser
from typing import TypedDict, cast
from dbt_ci.cache import CacheManager
from dbt_ci.graph.dependency_graph import DbtGraph
from dbt_ci.graph.graph_utils import get_deleted_nodes, get_new_nodes, get_node_from_path, get_nodes, get_structured_modified_nodes
from dbt_ci.logging import print_exception
from dbt_ci.runners import resolve_dbt_commands, run_dbt_command
from dbt_ci.schema import RunnerConfig, StateChangeSummary
from dbt_ci.utilities.git import GitAdapter

logger = logging.getLogger(__name__)

class CommonStateChangeSummary(TypedDict):
    modified_node_ids: set[str]
    deleted_node_ids: set[str]
    new_node_ids: set[str]

def get_state_modified(args: Namespace) -> StateChangeSummary:
    """Determines the modified, new, and deleted nodes compared to the reference state based on the specified comparison strategy."""
    strategy = getattr(args, "comparison_strategy")
    
    if strategy == "git":
        return git_strategy(args)
    elif strategy == "hybrid":
        return hybrid_strategy(args)
    elif strategy == "dbt":
        return dbt_strategy(args)
    else:
        logger.error(f"Invalid comparison strategy specified: {strategy}. Supported strategies are 'git', 'dbt', and 'hybrid'.")
        sys.exit(1)

def git_strategy(args: Namespace) -> StateChangeSummary:
    try:
        git = GitAdapter(args)
        target_graph = DbtGraph(args)
        target_dict = target_graph.to_dict()
        reference_graph = DbtGraph(args, is_reference=True)
        reference_dict = reference_graph.to_dict()
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


def hybrid_strategy(args: Namespace):
    """Determines modified nodes using dbt state:modified and then cross-references with git diff to filter out nodes that are not actually modified based on file changes."""
    try:
        git = GitAdapter(args)
        target_graph = DbtGraph(args).to_dict()
        reference_graph = DbtGraph(args, is_reference=True).to_dict()
        data = _common_state_change(args)
        changed_files = git.get_changed_files()
        modified_node_ids = data["modified_node_ids"]
        deleted_node_ids = data["deleted_node_ids"]
        new_node_ids = data["new_node_ids"]

        # Compare against git diff to determine what has been modified vs what is new
        temp_modified_nodes = get_nodes(
            dependency_graph=target_graph,
            node_ids=list(modified_node_ids)
        )

        # We now reference and check against git
        complete_modified_nodes = set()
        for node_id, node_info in temp_modified_nodes.items():
            file_path = node_info['original_file_path']
            if file_path in changed_files["modified"]:
                complete_modified_nodes.add(node_id)

        modified_node_ids = complete_modified_nodes

        state_change_summary: StateChangeSummary = {
            "modified_nodes": get_structured_modified_nodes(get_nodes(
                dependency_graph=target_graph, 
                node_ids=list(modified_node_ids)
            )),
            "deleted_nodes": get_structured_modified_nodes(get_nodes(
                dependency_graph=reference_graph, 
                node_ids=list(deleted_node_ids)
            )),
            "new_nodes": get_structured_modified_nodes(get_nodes(
                dependency_graph=target_graph, 
                node_ids=list(new_node_ids)
            ))
        }

        return state_change_summary
    except Exception as e:
        print_exception(e, "Error generating state change summary using hybrid strategy")
        sys.exit(1)

def dbt_strategy(args: Namespace) -> StateChangeSummary:
    """Compile the DBT project and return a list of modified nodes compared to the reference state."""
    try:
        target_graph = DbtGraph(args)
        reference_graph = DbtGraph(args, is_reference=True)
        data = _common_state_change(args)

        return {
            "modified_nodes": get_structured_modified_nodes(get_nodes(
                dependency_graph=target_graph.to_dict(), 
                node_ids=list(data["modified_node_ids"])
            )),
            "deleted_nodes": get_structured_modified_nodes(get_nodes(
                dependency_graph=reference_graph.to_dict(), 
                node_ids=list(data["deleted_node_ids"])
            )),
            "new_nodes": get_structured_modified_nodes(get_nodes(
                dependency_graph=target_graph.to_dict(), 
                node_ids=list(data["new_node_ids"])
            ))
        }
    except Exception as e:
        raise Exception(f"Error generating state change summary: {str(e)}")

def _common_state_change(args: Namespace) -> CommonStateChangeSummary:
    """
        Common logic to determine modified, new, and deleted nodes using 
        dbt's state:modified comparison, without git diff filtering. 
        This is used by both the dbt_strategy and hybrid_strategy functions 
        to avoid code duplication in the initial retrieval of modified nodes from dbt.
    """
    try:
        cache = CacheManager(args)
        target_graph = DbtGraph(args)
        reference_graph = DbtGraph(args, is_reference=True)

        commands = resolve_dbt_commands(["ls", "--select", "state:modified", "--output", "name", "--quiet"], args)
        commands.extend(["--target", getattr(args, "reference_target")])
        commands.extend(["--vars", getattr(args, "reference_vars")]) if getattr(args, "reference_vars", None) else None

        logger.debug(f"Running dbt ls command with arguments: {commands}")

        ls_output = run_dbt_command(
            command_args=commands,
            runner_config=cast(RunnerConfig, args.__dict__)
        )

        if ls_output is None:
            logger.info("No modified nodes found during initialization. Exiting...")
            cache.write_cache()
            sys.exit(0)

        modified_nodes = ls_output.stdout.splitlines()
        target_graph_dict = target_graph.to_dict()
        reference_graph_dict = reference_graph.to_dict()

        new_node_ids = set(get_new_nodes(reference_graph_dict, target_graph_dict) or [])
        deleted_node_ids = set(get_deleted_nodes(reference_graph_dict, target_graph_dict) or [])
        truly_modified_nodes = set([n for n in modified_nodes if n not in new_node_ids and n not in deleted_node_ids])

        return {
            "new_node_ids": new_node_ids,
            "deleted_node_ids": deleted_node_ids,
            "modified_node_ids": truly_modified_nodes
        }
    except Exception as e:
        print_exception(e, "Error generating state change summary")
        sys.exit(1)

if __name__ == "__main__":
    parser = ArgumentParser(description="Determine modified nodes compared to reference state using git strategy.")
    parser.add_argument(
        "--comparison-strategy", 
        choices=["git", "dbt", "hybrid"], 
        default="dbt", 
        help="Strategy to determine modified nodes. 'git' uses git diff, 'dbt' uses dbt's state:modified, and 'hybrid' uses a combination of both."
    )
    parser.add_argument(
        "--dbt-project-dir",
        type=str,
        help="Path to the DBT project directory.",
        default="data-models/dbt"
    )
    # Add other necessary arguments here (e.g. dbt_project_dir, reference_target, etc.)
    args = parser.parse_args()

    try:
        state_change_summary = get_state_modified(args)
        print(state_change_summary)
    except Exception as e:
        print_exception(e, "Error determining modified nodes")