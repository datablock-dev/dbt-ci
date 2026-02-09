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
        self.dir_path = Path(self.cache_dir).resolve()

    def write_cache(self, data: dict, file_name: str):
        """Write data to the cache file."""
        file_path = self.dir_path / file_name
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
            print(f"Cache written to {file_path.absolute()}")

    def get_cache(self, file_name: str) -> dict | None:
        """Load cache data from the cache file. Returns None if the file doesn't exist."""
        file_path = self.dir_path / file_name
        if file_path.is_file():
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            return None
