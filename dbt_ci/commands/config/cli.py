import click
from dbt_ci.main import cli
from dbt_ci.commands.config.index import generate_config
from dbt_ci.commands.config.show import render_json, render_table, resolve_settings


@cli.group(name="config", invoke_without_command=True)
@click.option(
    "--output",
    "-o",
    default="dbt-ci.config.yaml",
    show_default=True,
    help="Destination file path for the generated config.",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    default=False,
    help="Overwrite the file if it already exists.",
)
@click.pass_context
def config_cmd(ctx: click.Context, output: str, force: bool):
    """Generate a skeleton dbt-ci.config.yaml, or show resolved settings

    Without a subcommand this creates a commented configuration file with all common
    options pre-filled, so you can get started without memorising every flag.

    \b
    Examples:
        # Create dbt-ci.config.yaml in the current directory
        dbt-ci config

    \b
        # Write to a custom path
        dbt-ci config --output path/to/my-config.yaml

    \b
        # Overwrite an existing file
        dbt-ci config --force

    \b
        # Show what 'dbt-ci run --profile action' would run with
        dbt-ci config show run --profile action
    """
    if ctx.invoked_subcommand is None:
        generate_config(output=output, force=force)


@config_cmd.command(
    name="show",
    context_settings={"ignore_unknown_options": True, "allow_interspersed_args": False},
)
@click.option(
    "--all", "show_all", is_flag=True, default=False, help="Also list defaults and unset options."
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Print the result as JSON.")
@click.argument("command_line", nargs=-1, type=click.UNPROCESSED)
def config_show_cmd(show_all: bool, as_json: bool, command_line: tuple[str, ...]):
    """Show the settings a command would run with, and where each came from

    Pass the command and its flags as you would run them. They are combined with the
    config file, the selected profile, environment variables, what init recorded and the
    defaults, exactly as a real run would, but nothing is executed. Without a command,
    init is shown. Options of 'show' itself (--all, --json) go before the command.

    \b
    Examples:
        dbt-ci config show
        dbt-ci config show init --profile action
        dbt-ci config show --all run --mode models
        dbt-ci config show --json ephemeral destroy
    """
    resolved = resolve_settings(cli, list(command_line))
    click.echo(render_json(resolved, show_all) if as_json else render_table(resolved, show_all))
