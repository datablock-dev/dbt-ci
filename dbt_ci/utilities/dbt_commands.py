"""This module contains utility functions for DBT commands, such as compiling the reference state."""
import sys
import logging
from argparse import Namespace
from typing import cast
from dbt_ci.cache import CacheManager
from dbt_ci.graph.dependency_graph import DbtGraph
from dbt_ci.utilities.git import GitAdapter
from dbt_ci.schema import RunnerConfig, StateChangeSummary
from dbt_ci.runners import resolve_dbt_commands, run_dbt_command
from dbt_ci.utilities.paths import get_manifest_file
from dbt_ci.graph.graph_utils import get_deleted_nodes, get_new_nodes, get_nodes, get_structured_modified_nodes

logger = logging.getLogger(__name__)

def dbt_command_reference_compile(args: Namespace) -> None:
    """Compile the reference DBT project to generate the manifest.json."""
    try:

        if getattr(args, "skip_reference_compile", False):
            logger.info("Skipping reference compilation as per configuration.")
            return

        # This function can be called separately if users want to compile towards reference state independently, but by default it will be called during init if a different reference target is specified.
        command = ["compile"]
        reference_target = getattr(args, "reference_target", None)
        reference_vars = getattr(args, "reference_vars", None)
        if reference_target is None:
            logger.warning("No reference target specified, using current target as reference state for comparison.")
        else:
            command.extend(["--target", reference_target])
            command.extend(["--vars", reference_vars]) if reference_vars else None

        run_dbt_command(
            command_args=resolve_dbt_commands(
                command_args=command, 
                args=args, 
                ignore_keys=["vars", "target"] # Don't pass vars or target when compiling reference manifest
            ),
            runner_config=cast(RunnerConfig, args.__dict__)
        )

        logger.info("DBT project compiled successfully. manifest.json generated.")
    except Exception:
        logger.error("Error during reference compilation", exc_info=True)
        sys.exit(1)

def dbt_command_target_compile(args: Namespace, store_cache: bool = True) -> None:
    """Compile the target DBT project to generate the manifest.json."""
    try:
        cache = CacheManager(args)
        dbt_project_dir = getattr(args, "dbt_project_dir", None)
        target_command = ["compile"]
        target = getattr(args, "target", None)
        reference_target = getattr(args, "reference_target", None)
        is_reference_target_same_as_current = reference_target is None or reference_target == getattr(args, "target", None)
        
        if not getattr(args, "target_compile", False):
            # Removed now that skipping target compilation is the default behavior 
            # and users have to explicitly opt-in to compile towards target state by setting 
            # --target-compile flag to true.
            #logger.info("Skipping target compilation as per configuration.")
            return

        logger.info("Compiling towards target to generate manifest.json for target state.")

        if dbt_project_dir is None:
            logger.error("dbt_project_dir argument is required for target compilation.")
            sys.exit(1)
        
        if is_reference_target_same_as_current:
            logger.info("Reference target is the same as current target, skipping separate compilation for target state.")
            return

        if target and target != "default":
            target_command.extend(["--target", target])

        run_dbt_command(
            command_args=resolve_dbt_commands(target_command, args),
            runner_config=cast(RunnerConfig, args.__dict__)
        )

        if store_cache:
            target_manifest_file = get_manifest_file(dbt_project_dir)
            cache.write_target_manifest(target_manifest_file)

    except Exception:
        logger.error("Error during target compilation", exc_info=True)
        sys.exit(1)

"""
    To be deprecated and replaced by state_modified.py in commands/init/state_modified.py 
    which will be more comprehensive and accepts --comparison-strategy argument to 
    determine how to compare state (e.g. git diff vs dbt ls state:modified)
"""
def dbt_command_state_modified(args: Namespace):
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
        if getattr(args, "comparison_strategy") in ("git", "hybrid") and len(changed_files.keys()) > 0:
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