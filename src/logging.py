"""Logging configuration for the application."""
import logging
from typing import Literal

type LoggingLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

def setup_logging(level: LoggingLevel = "INFO") -> None:
    """Set up logging configuration."""
    logging.basicConfig(
        level=getattr(logging, level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )
