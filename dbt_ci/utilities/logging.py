"""Logging configuration for the application."""
import logging
import tempfile
from pathlib import Path
from dbt_ci.schema import LoggingLevel

logger = logging.getLogger(__name__)


class LogFileManager:
    """Writes all log records (regardless of level) to a file in the temp directory."""

    LOG_FORMAT = "[%(asctime)s][%(levelname)s]: %(message)s"
    DATE_FORMAT = "%Y-%m-%d %H:%M:%S.%f"[:-3]  # trim to milliseconds

    def __init__(self, log_dir: Path | None = None):
        self.log_dir = log_dir or Path(tempfile.gettempdir()) / "dbt-ci"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / "dbt-ci.log"
        self._handler: logging.FileHandler | None = None

    def attach(self) -> None:
        """Attach a DEBUG-level file handler to the root logger."""
        handler = logging.FileHandler(self.log_path, encoding="utf-8")
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(self.LOG_FORMAT, datefmt=self.DATE_FORMAT))
        logging.getLogger().addHandler(handler)
        self._handler = handler

    def detach(self) -> None:
        """Remove the file handler from the root logger."""
        if self._handler:
            logging.getLogger().removeHandler(self._handler)
            self._handler.close()
            self._handler = None


def setup_logging(level: LoggingLevel = "INFO") -> None:
    """Set up logging configuration."""
    logging.basicConfig(
        level=getattr(logging, level),
        format='%(message)s',
        force=True
    )
    LogFileManager().attach()

def print_exception(
    e: Exception,
    base_message: str = "Unexpected error", 
) -> None:
    """Print an exception with file and line number information."""
    logger.error(f"{base_message}: {e}")
    logger.error(f"File: {e.__traceback__.tb_frame.f_code.co_filename}")
    logger.error(f"Line: {e.__traceback__.tb_lineno}")