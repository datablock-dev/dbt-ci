"""
Ephemeral command for dbt-ci
"""

import sys
from argparse import Namespace
import click
from src.dependency_graph import DbtGraph
from src.variables import Variables


def ephemeral(**kwargs):
    """Run ephemeral CI check workflow
    
    Detects changes, lists modified models, but doesn't execute them.
    Useful for quick CI checks and PR previews.
    
    Examples:
        dbt-ci ephemeral --state prod-manifest/ --dbt-project-dir ./dbt
        dbt-ci ephemeral --state prod-manifest/ --runner docker
        
        # With environment variables
        export DBT_STATE=./dbt/.dbtstate/
        export DBT_PROJECT_DIR=./dbt
        dbt-ci ephemeral
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
        
        click.echo("🔍 Detecting modified models...")
        graph = DbtGraph(resolved_args)
        selector = "state:modified+"
        modified_nodes = graph.get_state_modified(selector=selector)
        
        if not modified_nodes:
            click.echo("✅ No modified models detected - no work to do!")
            return
        
        click.echo(f"\n📊 Changes detected: {len(modified_nodes)} modified model(s)")
        click.echo("\nModified models:")
        for node in modified_nodes:
            click.echo(f"  • {node}")
        
        click.echo(f"\n💡 To run these models, use: dbt-ci run --state {config.prod_manifest_dir}")
        
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)
