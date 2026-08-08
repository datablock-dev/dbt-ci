"""Run command for dbt-ci"""

import sys
import logging
from argparse import Namespace
import click
from dbt_ci.commands.run.run import run_nodes
from dbt_ci.graph.dependency_graph import DbtGraph
from dbt_ci.utilities.cache import CacheManager
from dbt_ci.utilities.logging import print_exception, redact_namespace
from dbt_ci.graph.graph_utils import get_node_ids_from_structured_nodes

logger = logging.getLogger(__name__)

def run(args: Namespace):
    """Run modified dbt models
    
    Detects models that have changed based on state comparison and runs them.
    
    Examples:
        dbt-ci run --state prod-manifest/ --dbt-project-dir ./dbt
        dbt-ci run --state prod-manifest/ --runner docker
        
        # With environment variables
        export DBT_STATE=./dbt/.dbtstate/
        export DBT_PROJECT_DIR=./dbt
        dbt-ci run
    """
    try:
        # Convert kwargs to Namespace and resolve configuration
        # Variables class handles type conversions (tuples->lists, string->bool, etc.)
        click.secho("DBT CI Run", fg="green", bold=True)
        logger.debug(f"Running with the following arguments: {redact_namespace(args)}")
        cache = CacheManager(args)
        cache.start_report("run", args)
        target_graph = DbtGraph(args)
                
        # Look for cache
        prev_cache = cache.get_cache()
        if prev_cache is None: # Should we exit here instead of compiling?
            logger.error("No cache found, please run 'dbt-ci init' first to generate the necessary manifest files and cache for comparison.")
            return
        logger.info("Cache successfully found - using cached state for comparison")

        changed_nodes_dict = {
            "modified_nodes": get_node_ids_from_structured_nodes(prev_cache.get("modified_nodes", None)) or [],
            "new_nodes": get_node_ids_from_structured_nodes(prev_cache.get("new_nodes", None)) or [],
            "deleted_nodes": get_node_ids_from_structured_nodes(prev_cache.get("deleted_nodes", None)) or []
        }
        changed_nodes = [value for values in changed_nodes_dict.values() for value in values]

        if len(changed_nodes) == 0:
            logger.info("No modified, new, or deleted nodes found in cache, skipping...")
            sys.exit(0)

        run_nodes(
            args=args,
            target_graph=target_graph,
            changed_nodes=changed_nodes,
            changed_nodes_dict=changed_nodes_dict
        )

        cache.update_report("run", "completed")
        logger.info("\nAll done!")
    except Exception as e:
        cache = CacheManager(args)
        cache.update_report("run", "failed", comment=str(e))
        print_exception(e)
        sys.exit(1)