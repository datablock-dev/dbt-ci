"""Logging configuration for the application."""
import logging
from src.schema import LoggingLevel

logger = logging.getLogger(__name__)

def setup_logging(level: LoggingLevel = "INFO") -> None:
    """Set up logging configuration."""
    logging.basicConfig(
        level=getattr(logging, level),
        format='%(message)s',
        force=True
    )

def print_exception(
    e: Exception,
    base_message: str = "Unexpected error", 
) -> None:
    """Print an exception with file and line number information."""
    logger.error(f"{base_message}: {e}")
    logger.error(f"File: {e.__traceback__.tb_frame.f_code.co_filename}")
    logger.error(f"Line: {e.__traceback__.tb_lineno}")