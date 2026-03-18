"""Implementation of the config command — generates a skeleton dbt-ci.config.yaml."""
import os
import sys
import logging
from pathlib import Path
import click

logger = logging.getLogger(__name__)

_SKELETON_PATH = Path(__file__).parent / "skeleton.config.yaml"


def _read_skeleton() -> str:
    return _SKELETON_PATH.read_text(encoding="utf-8")


# Expose for tests / schema assertions without hitting the filesystem repeatedly
SKELETON = _read_skeleton()


def generate_config(output: str, force: bool) -> None:
    """Write a skeleton dbt-ci.config.yaml to *output*."""
    if os.path.exists(output) and not force:
        click.secho(
            f"'{output}' already exists. Use --force to overwrite.",
            fg="yellow",
        )
        sys.exit(1)

    with open(output, "w", encoding="utf-8") as f:
        f.write(_read_skeleton())

    click.secho(f"Created {output}", fg="green", bold=True)
    logger.info(f"Config skeleton written to {output}")
