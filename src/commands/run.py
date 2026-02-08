"""
Run command for dbt-ci
"""

import sys
from argparse import Namespace
import click
from src.dependency_graph import DbtGraph
from src.runners import run_dbt_command
from src.variables import Variables


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
        resolved_args.mode = 'run'
        resolved_args.log_file = None

        print(resolved_args)
        
        # Detect modified models using the dependency graph and run them
        click.echo("🔍 Detecting modified models...")
        graph = DbtGraph(resolved_args)
        selector = "state:modified"
        modified_nodes = graph.get_state_modified(selector=selector)
        
        if not modified_nodes:
            click.echo("✅ No modified models detected")
            return
        
        click.echo(f"📊 Found {len(modified_nodes)} modified model(s):")
        for node in modified_nodes:
            click.echo(f"  • {node}")
        
        click.echo("\n🚀 Running modified models...")
        
        # Build dbt run command with selector
        run_args = ["run", "--select", selector]
        
        result = run_dbt_command(
            command_args=run_args,
            runner_config=graph._get_runner_config(),
            quiet=False
        )
        
        if result and result.returncode == 0:
            click.echo(f"\n✅ Successfully ran {len(modified_nodes)} model(s)")
        else:
            click.echo("\n❌ Run failed", err=True)
            sys.exit(1)
            
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)
