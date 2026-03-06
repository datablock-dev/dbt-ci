"""
    CacheManager class for handling caching of data in JSON files,
    and managing the report.json for tracking command execution status and variables.
"""
import json
import tempfile
import logging
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from src.schema import Commands

logger = logging.getLogger(__name__)

class CacheManager:
    """
        Simple cache manager for storing and retrieving data in a JSON file, 
        using tempfile for cache directory by default.
    """
    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or Path(tempfile.gettempdir()) / "dbt_ci_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.dir_path = Path(self.cache_dir).resolve()

    def write_cache(self, data: dict[str, Any], file_name: str = "cache.json"):
        """Write data to the cache file."""
        file_path = self.dir_path / file_name
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(
                obj=data,
                fp=f,
                indent=4,
                default=lambda o: list(o) if isinstance(o, set) else o
            )
            logger.debug(f"Cache written to {file_path.absolute()}")

    def get_cache(self, file_name: str = "cache.json") -> dict[str, Any] | None:
        """Load cache data from the cache file. Returns None if the file doesn't exist."""
        file_path = self.dir_path / file_name
        if file_path.is_file():
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            return None

    def _write_report(self, data: dict[str, Any]):
        """Write data to the report.json file."""
        self.write_cache(data, "report.json")        

    def start_report(self, command: Commands, args: Namespace):
        """Add information to report.json"""
        if command == "init":
            # Clear previous report on init
            self._write_report({})
        # Check if key exists in cache, if not create it
        report_cache = self.get_cache("report.json")
        if report_cache is None:
            self._write_report({
                command: {
                    "status": "started",
                    "started_at": datetime.now().isoformat(),
                    "variables": {
                        "runner": getattr(args, "runner", None),
                        "target": getattr(args, "target", None),
                        "reference_target": getattr(args, "reference_target", None),
                    }
                }
            })
        else:
            report_cache[command] = {
                "status": "started",
                "started_at": datetime.now().isoformat(),
                "variables": {
                    "runner": getattr(args, "runner", None),
                    "target": getattr(args, "target", None),
                    "reference_target": getattr(args, "reference_target", None),
                }
            }
            self._write_report(report_cache)

    def update_report(self, command: Commands, status: str, comment: dict[str, Any] | str | None = None):
        """Update report.json with status and timestamp"""
        report_cache = self.get_cache("report.json")
        if report_cache is not None and command in report_cache:
            report_cache[command]["status"] = status
            report_cache[command][f"{status}_at"] = datetime.now().isoformat()
            if comment:
                if isinstance(comment, dict):
                    for key, value in comment.items():
                        report_cache[command][key] = value
                else:
                    report_cache[command]["comment"] = comment
            self._write_report(report_cache)
