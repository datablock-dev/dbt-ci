import logging
from argparse import Namespace
from dbt_ci.cache import CacheManager
from dbt_ci.graph.dependency_graph import DbtGraph
from dbt_ci.logging import print_exception
from dbt_ci.schema import StateChangeSummary
from dbt_ci.utilities.git import GitAdapter

logger = logging.getLogger(__name__)

def git_state_modified(args: Namespace) -> StateChangeSummary:
    try:
        git = GitAdapter(args)
        cache = CacheManager(args)
        target_graph = DbtGraph(args)
        reference_graph = DbtGraph(args, is_reference=True)
        changed_files = git.get_changed_files()
        modified_nodes = set()

        # Get modified nodes based on git diff
        for node_type, node_values in target_graph.to_dict().items():
            for node_id, node_info in node_values.items():
                file_path = node_info['original_file_path']
                if file_path in changed_files["modified"]:
                    modified_nodes.add(node_id)
                elif 

        return StateChangeSummary(
            modified_nodes=list(modified_nodes),
            deleted_nodes=[],
            new_nodes=[]
        )
    except Exception as e:
        print_exception(e, "Error generating state change summary using git strategy")


def hybrid_state_modified(args: Namespace):


def dbt_state_modified(args: Namespace) -> StateChangeSummary:
    """Compile the DBT project and return a list of modified nodes compared to the reference state."""
    try:
        git = GitAdapter(args)
        cache = CacheManager(args)
        target_graph = DbtGraph(args)
        reference_graph = DbtGraph(args, is_reference=True)

        changed_files = git.get_changed_files()

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
        truly_modified_nodes = [n for n in modified_nodes if n not in new_node_ids and n not in deleted_node_ids]

        # Compare against git diff to determine what has been modified vs what is new
        if getattr(args, "no_git", False) is False and len(changed_files.keys()) > 0:
            temp_modified_nodes = get_nodes(
                dependency_graph=target_graph_dict,
                node_ids=truly_modified_nodes
            )

            # We now reference and check against git
            complete_modified_nodes = set()
            for node_id, node_info in temp_modified_nodes.items():
                file_path = node_info['original_file_path']
                if file_path in changed_files["modified"]:
                    complete_modified_nodes.add(node_id)

            truly_modified_nodes = list(complete_modified_nodes)

        state_change_summary: StateChangeSummary = {
            "modified_nodes": get_structured_modified_nodes(get_nodes(
                dependency_graph=target_graph_dict, 
                node_ids=truly_modified_nodes
            )),
            "deleted_nodes": get_structured_modified_nodes(get_nodes(
                dependency_graph=reference_graph_dict, 
                node_ids=list(deleted_node_ids)
            )),
            "new_nodes": get_structured_modified_nodes(get_nodes(
                dependency_graph=target_graph_dict, 
                node_ids=list(new_node_ids)
            ))
        }

        return state_change_summary
    except Exception as e:
        raise Exception(f"Error generating state change summary: {str(e)}")