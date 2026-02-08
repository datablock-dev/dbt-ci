import sys
import click
from src.dependency_graph import DbtGraph
from src.runners import run_dbt_command
from argparse import Namespace


# Shared options for all commands
def common_options(f):
    """Decorator to add common options to all commands"""
    f = click.option(
        '--prod-manifest-dir', 
        '--reference-manifest-dir', 
        '--state',
        required=True,
        help='Path to the production/reference manifest.json directory'
    )(f)
    f = click.option(
        '--dbt-project-dir', 
        default='.',
        help='Path to the dbt project directory (default: current directory)'
    )(f)
    f = click.option(
        '--profiles-dir', 
        default=None,
        help='Path to the directory containing the dbt profiles.yml file'
    )(f)
    f = click.option(
        '--target', 
        '-t', 
        default=None,
        help='The dbt target to use (defaults to what is defined in profiles.yml)'
    )(f)
    f = click.option(
        '--vars', 
        '-v', 
        default='',
        help='A YAML string or path to YAML file containing variables to pass to dbt'
    )(f)
    f = click.option(
        '--runner', 
        '-r', 
        type=click.Choice(['local', 'docker', 'bash', 'dbt']),
        default='dbt', 
        help='Runner to use for executing dbt commands'
    )(f)
    f = click.option(
        '--entrypoint', 
        default='dbt',
        help='Command entrypoint for dbt (default: dbt)'
    )(f)
    f = click.option(
        '--dry-run', 
        is_flag=True, 
        default=False,
        help='Print commands without executing them'
    )(f)
    f = click.option(
        '--log-level', 
        type=click.Choice(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']),
        default='INFO', 
        help='Logging level'
    )(f)
    
    # Docker options
    f = click.option(
        '--docker-image', 
        default='ghcr.io/dbt-labs/dbt-core:latest',
        help='Docker image to use'
    )(f)
    f = click.option(
        '--docker-platform', 
        default=None,
        help='Platform for Docker (e.g., linux/amd64)'
    )(f)
    f = click.option(
        '--docker-volumes', 
        multiple=True, 
        default=[],
        help='Additional volume mounts (format: host:container)'
    )(f)
    f = click.option(
        '--docker-env', 
        multiple=True, 
        default=[],
        help='Environment variables (format: KEY=VALUE)'
    )(f)
    f = click.option(
        '--docker-network', 
        default='host',
        help='Docker network mode'
    )(f)
    f = click.option(
        '--docker-user', 
        default=None,
        help='User to run as inside container'
    )(f)
    f = click.option(
        '--docker-args', 
        default='',
        help='Additional docker run arguments'
    )(f)
    
    # Bash options
    f = click.option(
        '--shell-path', 
        '--bash-path', 
        default='/bin/bash',
        help='Path to shell executable for bash runner'
    )(f)
    
    return f


@click.group()
@click.version_option(version='0.1.0', prog_name='dbt-ci')
def cli():
    """dbt CI Tool - Intelligent CI for dbt projects
    
    Detect, run, and test only what changed based on state comparison.
    
    Visit https://datablock.dev for more information.
    """
    pass


@cli.command()
@common_options
def run(
    prod_manifest_dir,
    dbt_project_dir,
    profiles_dir,
    target,
    vars,
    runner,
    entrypoint,
    dry_run,
    log_level,
    docker_image,
    docker_platform,
    docker_volumes,
    docker_env,
    docker_network,
    docker_user,
    docker_args,
    shell_path
):
    """Run modified dbt models
    
    Detects models that have changed based on state comparison and runs them.
    
    Examples:
        dbt-ci run --state prod-manifest/ --dbt-project-dir ./dbt
        dbt-ci run --state prod-manifest/ --select "state:modified+" --runner docker
        dbt-ci run --state prod-manifest/ --full-refresh
    """
    try:
        # Create args namespace for DbtGraph compatibility
        args = Namespace(
            prod_manifest_dir=prod_manifest_dir,
            dbt_project_dir=dbt_project_dir,
            profiles_dir=profiles_dir,
            target=target,
            vars=vars,
            runner=runner,
            entrypoint=entrypoint,
            dry_run=dry_run,
            log_level=log_level,
            docker_image=docker_image,
            docker_platform=docker_platform,
            docker_volumes=list(docker_volumes),
            docker_env=list(docker_env),
            docker_network=docker_network,
            docker_user=docker_user,
            docker_args=docker_args,
            shell_path=shell_path,
            mode='run',
            log_file=None
        )
        
        click.echo(f"🔍 Detecting modified models...")
        graph = DbtGraph(args)
        modified_nodes = graph.get_state_modified()
        
        if not modified_nodes:
            click.echo("✅ No modified models detected")
            return
        
        click.echo("📊 Found {len(modified_nodes)} modified model(s):")
        for node in modified_nodes:
            click.echo(f"  • {node}")
        
        click.echo("\n🚀 Running modified models...")
        
        # Build dbt run command
        run_args = [
            "run",
            "--select", select,
            *(["--full-refresh"] if full_refresh else [])
        ]
        
        result = run_dbt_command(
            command_args=run_args,
            runner_config=graph._get_runner_config(),
            quiet=False
        )
        
        if result and result.returncode == 0:
            click.echo("\n✅ Successfully ran {len(modified_nodes)} model(s)")
        else:
            click.echo("\n❌ Run failed", err=True)
            sys.exit(1)
            
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@common_options
def ephemeral(
    prod_manifest_dir, 
    dbt_project_dir,
    profiles_dir,
    target,
    vars,
    runner,
    entrypoint,
    dry_run,
    log_level,
    docker_image,
    docker_platform,
    docker_volumes,
    docker_env,
    docker_network,
    docker_user,
    docker_args,
    shell_path
):
    """Run ephemeral CI check workflow
    
    Detects changes, lists modified models, but doesn't execute them.
    Useful for quick CI checks and PR previews.
    
    Examples:
        dbt-ci ephemeral --state prod-manifest/ --dbt-project-dir ./dbt
        dbt-ci ephemeral --state prod-manifest/ --runner docker
    """
    try:
        from argparse import Namespace
        args = Namespace(
            prod_manifest_dir=prod_manifest_dir,
            dbt_project_dir=dbt_project_dir,
            profiles_dir=profiles_dir,
            target=target,
            vars=vars,
            runner=runner,
            entrypoint=entrypoint,
            dry_run=dry_run,
            log_level=log_level,
            docker_image=docker_image,
            docker_platform=docker_platform,
            docker_volumes=list(docker_volumes),
            docker_env=list(docker_env),
            docker_network=docker_network,
            docker_user=docker_user,
            docker_args=docker_args,
            shell_path=shell_path,
            mode='run',
            selector=select,
            log_file=None
        )
        
        click.echo(f"🔍 Detecting modified models...")
        graph = DbtGraph(args)
        modified_nodes = graph.get_state_modified(selector=select)
        
        if not modified_nodes:
            click.echo("✅ No modified models detected - no work to do!")
            return
        
        click.echo(f"\n📊 Changes detected: {len(modified_nodes)} modified model(s)")
        click.echo("\nModified models:")
        for node in modified_nodes:
            click.echo(f"  • {node}")
        
        click.echo(f"\n💡 To run these models, use: dbt-ci run --state {prod_manifest_dir}")
        
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()

