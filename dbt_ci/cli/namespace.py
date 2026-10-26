"""Turn a Click command's keyword arguments into the Namespace the commands take."""

import logging
from argparse import Namespace

logger = logging.getLogger(__name__)


def to_namespace(kwargs, command=None):
    """Convert a Click command's keyword arguments into an argparse.Namespace."""
    if command:
        kwargs["command"] = command

    return Namespace(**kwargs)
