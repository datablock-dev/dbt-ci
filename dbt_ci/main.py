# Shared options for all commands
import click

def get_version():
    try:
        import importlib.metadata as importlib_metadata
    except ImportError:
        import importlib_metadata
    return importlib_metadata.version("dbt-ci")

@click.group()
@click.version_option(version=get_version(), prog_name='dbt-ci')
def cli():
    """dbt CI Tool - Intelligent CI for dbt projects
    
    Detect, run, and test only what changed based on state comparison.
    
    Visit https://datablock.dev for more information.
    """
    pass

# Import command modules to register them with the cli group
import dbt_ci.commands.init.cli       # noqa: E402, F401
import dbt_ci.commands.run.cli        # noqa: E402, F401
import dbt_ci.commands.ephemeral.cli  # noqa: E402, F401
import dbt_ci.commands.delete.cli     # noqa: E402, F401
import dbt_ci.commands.migration.cli  # noqa: E402, F401
import dbt_ci.commands.finalize.cli   # noqa: E402, F401
import dbt_ci.commands.config.cli     # noqa: E402, F401

if __name__ == "__main__":
    cli()