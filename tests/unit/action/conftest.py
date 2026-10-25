"""Make the GitHub Action's entrypoint package importable; it lives outside dbt_ci."""
import sys
from pathlib import Path

ACTION_DIR = Path(__file__).resolve().parents[3] / "action"
if str(ACTION_DIR) not in sys.path:
    sys.path.insert(0, str(ACTION_DIR))
