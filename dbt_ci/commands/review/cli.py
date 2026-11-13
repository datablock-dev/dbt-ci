import click
from dbt_ci.main import cli
from dbt_ci.cli.common_options import common_options
from dbt_ci.cli.config import make_config_callback
from dbt_ci.cli.namespace import to_namespace
from dbt_ci.commands.review.claude import DEFAULT_EFFORT, DEFAULT_MODEL, EFFORTS
from dbt_ci.commands.review.index import review
from dbt_ci.utilities.logging import setup_logging


@cli.command(name="review")
@common_options(dry_run_section="review")
@click.option(
    "--model",
    envvar=["DBT_REVIEW_MODEL"],
    default=DEFAULT_MODEL,
    callback=make_config_callback("DBT_REVIEW_MODEL"),
    help=f"Claude model that reviews the changes (default: {DEFAULT_MODEL}).",
)
@click.option(
    "--effort",
    envvar=["DBT_REVIEW_EFFORT"],
    type=click.Choice(EFFORTS, case_sensitive=False),
    default=DEFAULT_EFFORT,
    callback=make_config_callback("DBT_REVIEW_EFFORT", then=str.lower),
    help=f"How hard the model thinks about each batch (default: {DEFAULT_EFFORT}).",
)
@click.option(
    "--max-models",
    envvar=["DBT_REVIEW_MAX_MODELS"],
    type=click.IntRange(min=1),
    default=20,
    callback=make_config_callback("DBT_REVIEW_MAX_MODELS"),
    help=(
        "Review at most this many changed models; the ones with the longest recorded "
        "run time are kept (default: 20)."
    ),
)
@click.option(
    "--exclude",
    envvar=["DBT_REVIEW_EXCLUDE"],
    multiple=True,
    default=None,
    callback=make_config_callback("DBT_REVIEW_EXCLUDE"),
    help="Leave out models whose path matches this pattern, e.g. 'models/legacy/*'. Repeatable.",
)
@click.option(
    "--instructions",
    envvar=["DBT_REVIEW_INSTRUCTIONS"],
    default=None,
    callback=make_config_callback("DBT_REVIEW_INSTRUCTIONS"),
    help="Extra guidance for the reviewer, such as your team's conventions.",
)
@click.option(
    "--fail-on",
    envvar=["DBT_REVIEW_FAIL_ON"],
    type=click.Choice(["high", "medium", "low", "never"], case_sensitive=False),
    default="never",
    callback=make_config_callback("DBT_REVIEW_FAIL_ON", then=str.lower),
    help="Exit 1 when a finding is at least this severe (default: never).",
)
@click.option(
    "--output",
    "-o",
    envvar=["DBT_REVIEW_OUTPUT"],
    default=None,
    type=str,
    callback=make_config_callback("DBT_REVIEW_OUTPUT"),
    help="Where to write the review (default: stdout). 'report' shows it either way.",
)
@click.option(
    "--format",
    "-F",
    "format",
    envvar=["DBT_REVIEW_FORMAT"],
    type=click.Choice(["markdown", "json"], case_sensitive=False),
    default="markdown",
    callback=make_config_callback("DBT_REVIEW_FORMAT", then=str.lower),
    help="Output format (default: markdown).",
)
def review_cmd(**kwargs):
    """Review the changed models with Claude (AI)

    Sends the SQL and metadata of the models 'init' found changed to Claude, and records
    its findings for 'report', which shows them in the job summary and PR comment. No
    warehouse data is sent. Needs 'pip install dbt-ci[ai]' and ANTHROPIC_API_KEY.

    \b
    Examples:
        dbt-ci init ... && dbt-ci review && dbt-ci report --pr-comment

    \b
        # Fail the job on high-severity findings
        dbt-ci review --fail-on high
    """
    setup_logging(to_namespace(kwargs).log_level)
    return review(to_namespace(kwargs, command="review"))
