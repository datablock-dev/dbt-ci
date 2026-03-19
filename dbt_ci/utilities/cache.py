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
from typing import Any, Optional, cast
from dbt_ci.schema import Commands, DBTManifest, DbtCiManifest, EphemeralMapNode, StateChangeSummary, SupportedConnectors
from dbt_ci.utilities.paths import get_profile

logger = logging.getLogger(__name__)

class CacheManager:
    """
        Simple cache manager for storing and retrieving data in a JSON file, 
        using tempfile for cache directory by default.
    """
    def __init__(self, args: Namespace, cache_dir: Optional[Path] = None):
        self.args = args
        self.cache_dir = cache_dir or Path(tempfile.gettempdir()) / "dbt-ci"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.dir_path = self.cache_dir.resolve()

    def write_cache(self, data: StateChangeSummary | None = None) -> None:
        """Write data to the cache file."""
        connector_type = cast(SupportedConnectors, get_profile(self.args)["type"])

        payload: DbtCiManifest = {
            "modified_nodes": data.get("modified_nodes") if data else None,
            "new_nodes": data.get("new_nodes") if data else None,
            "deleted_nodes": data.get("deleted_nodes") if data else None,
            "config": {
                "connector": connector_type,
                "comparison_strategy": getattr(self.args, "comparison_strategy"),
                "runner": getattr(self.args, "runner"),
                "reference": {
                    "target": getattr(self.args, "reference_target", None),
                    "vars": getattr(self.args, "reference_vars", None),
                },
                "target": {
                    "target": getattr(self.args, "target", None),
                    "vars": getattr(self.args, "vars", None),
                }
            }
        }
        self._write(cast(dict, payload), "cache.json")

    def _file_path(self, file_name: str) -> Path:
        return self.dir_path / file_name

    def _write(self, data: dict[str, Any], file_name: str):
        """Write data to the cache file."""
        file_path = self._file_path(file_name)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(
                obj=data,
                fp=f,
                indent=4,
                default=lambda o: list(o) if isinstance(o, set) else o
            )
            logger.debug(f"Cache written to {file_path.absolute()}")

    def write_ephemeral(self, data: dict[str, EphemeralMapNode]) -> None:
        """Write ephemeral map data to a JSON file in the cache directory."""
        self._write(cast(dict, data), "ephemeral_map.json")

    def write_reference_manifest(self, manifest_data: DBTManifest):
        """Write reference manifest data to a JSON file in the cache directory."""
        self._write(cast(dict, manifest_data), "reference_manifest.json")

    def write_target_manifest(self, manifest_data: DBTManifest) -> None:
        """Write manifest data to a JSON file in the cache directory."""
        self._write(cast(dict, manifest_data), "target_manifest.json")

    def write_reference_graph(self, graph_data: dict[str, Any]) -> None:
        """Write reference graph data to a JSON file in the cache directory."""
        self._write(cast(dict, graph_data), "reference_graph.json")
    
    def get_reference_graph(self) -> dict[str, Any] | None:
        """Load reference graph data from the cache file. Returns None if the file doesn't exist."""
        return cast(dict[str, Any], self.get_cache("reference_graph.json"))

    def write_target_graph(self, graph_data: dict[str, Any]) -> None:
        """Write target graph data to a JSON file in the cache directory."""
        self._write(cast(dict, graph_data), "target_graph.json")
    
    def get_target_graph(self) -> dict[str, Any] | None:
        """Load target graph data from the cache file. Returns None if the file doesn't exist."""
        return cast(dict[str, Any], self.get_cache("target_graph.json"))

    def get_cache(self, file_name: str = "cache.json", content_type: str = "json") -> dict[str, Any] | str | None:
        """Load cache data from the cache file. Returns None if the file doesn't exist."""
        file_path = self._file_path(file_name)
        if file_path.is_file():
            with open(file_path, 'r', encoding='utf-8') as f:
                if content_type == "json":
                    return json.load(f)
                elif content_type == "txt":
                    return f.read()
        else:
            return None

    def _write_report(self, data: dict[str, Any]):
        """Write data to the report.json file."""
        self._write(data, "report.json")        

    def start_report(self, command: Commands, args: Namespace):
        """Add information to report.json"""
        report_cache = {} if command == "init" else (cast(dict[str, Any], self.get_cache("report.json")) or {})
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
        report_cache = cast(dict[str, Any], self.get_cache("report.json"))
        if report_cache is None or command not in report_cache:
            logger.warning(f"update_report called for '{command}' but no existing report entry found. Call start_report first.")
            return
        report_cache[command]["status"] = status
        report_cache[command][f"{status}_at"] = datetime.now().isoformat()
        if comment:
            if isinstance(comment, dict):
                for key, value in comment.items():
                    report_cache[command][key] = value
            else:
                report_cache[command]["comment"] = comment
        self._write_report(report_cache)

    def clear_cache(self) -> None:
        """Clear the cache by deleting the files in the folder"""
        if self.dir_path.is_dir():
            for file in self.dir_path.iterdir():
                file.unlink()
            logger.info(f"Cache cleared from {self.dir_path.absolute()}")
