import json
import tempfile
from pathlib import Path
from typing import Optional

class CacheManager:
    """
        Simple cache manager for storing and retrieving data in a JSON file, 
        using tempfile for cache directory by default.
    """
    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or Path(tempfile.gettempdir()) / "dbt_ci_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.file_name = "dbt_ci_cache.json"
        self.file_path = Path(self.cache_dir / self.file_name).resolve()

    def write_cache(self, data: dict):
        """Write data to the cache file."""
        with open(self.file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)

    def get_cache(self) -> dict | None:
        """Load cache data from the cache file. Returns None if the file doesn't exist."""
        if self.file_path.is_file():
            with open(self.file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            return None
