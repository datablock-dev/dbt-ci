"""Logging configuration for the application."""
import logging
from src.schema import LoggingLevel

def setup_logging(level: LoggingLevel = "INFO") -> None:
    """Set up logging configuration."""
    logging.basicConfig(
        level=getattr(logging, level),
        format='%(message)s',
        force=True
    )
