import click
from dbt_ci.main import cli
from dbt_ci.cli.common_options import common_options
from dbt_ci.cli.config import make_config_callback
from dbt_ci.cli.namespace import to_namespace
from dbt_ci.utilities.logging import setup_logging
from dbt_ci.commands.report.index import report


@cli.command(name="report")
@common_options
@click.option(
    "--output", "-o",
    envvar=["DBT_REPORT_OUTPUT"],
    default=None,
    type=str,
    callback=make_config_callback("DBT_REPORT_OUTPUT"),
    help=(
        "Where to write the report. Defaults to $GITHUB_STEP_SUMMARY when set, "
        "otherwise stdout."
    ),
)
@click.option(
    "--format", "-F", "format",
    envvar=["DBT_REPORT_FORMAT"],
    type=click.Choice(["markdown", "json"], case_sensitive=False),
    default="markdown",
    callback=make_config_callback("DBT_REPORT_FORMAT", then=str.lower),
    help="Output format (default: markdown).",
)
def report_cmd(**kwargs):
    """Summarise the current dbt-ci run

    Renders the change set from 'init' and the status of each command that has run so
    far. In GitHub Actions the report is appended to the job summary automatically.

    Examples:
        # Append to the GitHub Actions job summary
        dbt-ci report

        # Write markdown to a file, e.g. to post as a pull request comment
        dbt-ci report --output report.md

        # Machine-readable output
        dbt-ci report --format json
    """
    setup_logging(to_namespace(kwargs).log_level)
    return report(to_namespace(kwargs, command="report"))
