import click
from dbt_ci.main import cli
from dbt_ci.commands.config.index import generate_config


@cli.command(name="config")
@click.option(
    "--output", "-o",
    default="dbt-ci.config.yaml",
    show_default=True,
    help="Destination file path for the generated config.",
)
@click.option(
    "--force", "-f",
    is_flag=True,
    default=False,
    help="Overwrite the file if it already exists.",
)
def config_cmd(output: str, force: bool):
    """Generate a skeleton dbt-ci.config.yaml

    Creates a commented configuration file with all common options pre-filled
    so you can get started quickly without memorising every flag.

    Examples:
        # Create dbt-ci.config.yaml in the current directory
        dbt-ci config

        # Write to a custom path
        dbt-ci config --output path/to/my-config.yaml

        # Overwrite an existing file
        dbt-ci config --force
    """
    generate_config(output=output, force=force)
