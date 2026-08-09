"""Logging configuration for the application."""
import logging
from argparse import Namespace
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from dbt_ci.schema import LoggingLevel
from dbt_ci.utilities.paths import get_cache_dir

logger = logging.getLogger(__name__)

# Name of the log file inside the cache directory. Shared with CacheManager, which must
# not delete this file while a handler still holds it open.
LOG_FILE_NAME = "dbt-ci.log"


class LogFileManager:
    """Writes all log records (regardless of level) to a file in the cache directory."""

    LOG_FORMAT = "[%(asctime)s][%(levelname)s]: %(message)s"
    DATE_FORMAT = "%Y-%m-%d %H:%M:%S.%f"[:-3]  # trim to milliseconds

    def __init__(self, log_dir: Path | None = None):
        self.log_dir = log_dir or get_cache_dir()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / LOG_FILE_NAME
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

def flush_log_file() -> None:
    """Flush buffered log records to disk so the log file can be read or uploaded."""
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.FileHandler):
            handler.flush()

# Substrings marking a configuration value as sensitive. The file log always records at
# DEBUG level and can be uploaded by `finalize --files log`, so anything logged here can
# leave the CI runner.
SENSITIVE_KEY_MARKERS = ("webhook", "token", "password", "secret", "credential", "api_key")

REDACTED = "***"

def redact(value: Any, key: str = "") -> Any:
    """
    Return a copy of a config value with anything secret-looking masked.

    Mappings and sequences are walked recursively, and 'KEY=VALUE' strings (as used by
    --docker-env and --docker-args) have their value masked when the key looks sensitive.
    """
    if _is_sensitive(key):
        return REDACTED

    if isinstance(value, Mapping):
        return {k: redact(v, str(k)) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return type(value)(redact(item) for item in value)

    if isinstance(value, str) and "=" in value:
        # Environment-variable style entries: mask the value, keep the name.
        name, _, raw = value.partition("=")
        if _is_sensitive(name):
            return f"{name}={REDACTED}"

    return value

def redact_namespace(namespace: Namespace) -> dict[str, Any]:
    """Return a namespace's contents as a dict with sensitive values masked, for logging."""
    return {key: redact(value, key) for key, value in vars(namespace).items()}

def _is_sensitive(key: str) -> bool:
    """Report whether a configuration key name suggests it holds a secret."""
    lowered = key.lower()
    return any(marker in lowered for marker in SENSITIVE_KEY_MARKERS)

def print_exception(
    e: Exception,
    base_message: str = "Unexpected error", 
) -> None:
    """Print an exception with file and line number information."""
    logger.error(f"{base_message}: {e}")
    logger.error(f"File: {e.__traceback__.tb_frame.f_code.co_filename}")
    logger.error(f"Line: {e.__traceback__.tb_lineno}")