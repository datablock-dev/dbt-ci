"""
Run command for dbt-ci
"""

import sys
from argparse import Namespace
import click
from src.dependency_graph import DbtGraph
from src.schema import RunnerConfig
from src.variables import Variables
from src.cache import CacheManager
from src.runners import run_dbt_command, append_dbt_variables_to_command

def run(**kwargs):
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
        # Convert kwargs to Namespace for Variables resolution
        args = Namespace(**kwargs)
        cache = CacheManager()
        
        # Handle docker_volumes and docker_env which come as tuples from Click
        if 'docker_volumes' in kwargs:
            args.docker_volumes = list(kwargs['docker_volumes']) if kwargs['docker_volumes'] else []
        if 'docker_env' in kwargs:
            args.docker_env = list(kwargs['docker_env']) if kwargs['docker_env'] else []
        
        # Resolve configuration from flags, env vars, and defaults
        # This will validate required fields and apply precedence
        config = Variables(args)
        
        # Create namespace with resolved values for DbtGraph
        resolved_args = config.to_namespace()
        resolved_args.mode = 'run' # why?
        resolved_args.log_file = None # why?
        
        # Look for cache
        prev_cache = cache.get_cache("dbt_ci_state.json")
        if prev_cache is None:
            click.echo("No cache found, compiling DBT")
            run_dbt_command(
                command_args=append_dbt_variables_to_command(["compile"], resolved_args),
                runner_config=RunnerConfig(resolved_args.__dict__),
                quiet=False
            )
        else:
            click.echo("Cache found, skipping compile")
            print(prev_cache)


        # Detect modified models using the dependency graph and run them
        click.echo("🔍 Detecting modified models...")
        graph = DbtGraph(resolved_args)
        modified_nodes = graph.get_state_modified()
        #cache.write_cache(graph.to_dict())
        
        if not modified_nodes:
            click.echo("✅ No modified models detected")
            return
        
        click.echo(f"📊 Found {len(modified_nodes)} modified model(s):")
        for node in modified_nodes:
            click.echo(f"  • {node}")
        
        click.echo("\n🚀 Running modified models...")
        
        # Build dbt run command with selector
        result = run_dbt_command(
            command_args=append_dbt_variables_to_command(["run", "--select", " ".join(modified_nodes)], resolved_args),
            runner_config=RunnerConfig(resolved_args.__dict__),
            quiet=False
        )

        print(f"Test result: {result.stdout}")
        
        if result and result.returncode == 0:
            click.echo(f"\n✅ Successfully ran {len(modified_nodes)} model(s)")
        else:
            click.echo("\n❌ Run failed", err=True)
            sys.exit(1)
            
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)
