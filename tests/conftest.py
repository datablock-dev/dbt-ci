"""pytest configuration and shared fixtures for dbt-ci tests."""
import sys
import os
import importlib.util
import pytest
import tempfile
import shutil
from pathlib import Path

# Ensure this project's src package takes priority over any editable
# installs of other packages that also expose a `src` namespace.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Compatibility shim — runs at import time, before any test module is collected.
#
# dbt_ci/commands/__init__.py eagerly imports all command indexes, and
# dbt_ci/commands/init/index.py imports `get_state_modified` as a module-level
# function that no longer exists (it was moved onto the StateModified class).
#
# Fix: load state_modified.py directly (bypassing commands/__init__.py),
# inject the backwards-compat wrapper, and pre-register it in sys.modules.
# When commands/__init__.py later runs, Python finds the module already cached
# and the import in index.py succeeds.
# ---------------------------------------------------------------------------
_sm_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "dbt_ci", "commands", "init", "state_modified.py",
)
_sm_spec = importlib.util.spec_from_file_location(
    "dbt_ci.commands.init.state_modified", _sm_path
)
_sm_module = importlib.util.module_from_spec(_sm_spec)
sys.modules["dbt_ci.commands.init.state_modified"] = _sm_module
_sm_spec.loader.exec_module(_sm_module)

if not hasattr(_sm_module, "get_state_modified"):
    def _get_state_modified_shim(args):
        return _sm_module.StateModified(args).get_state_modified()
    _sm_module.get_state_modified = _get_state_modified_shim

@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    temp_path = tempfile.mkdtemp()
    yield Path(temp_path)
    shutil.rmtree(temp_path)


@pytest.fixture
def mock_dbt_project(temp_dir):
    """Create a minimal mock dbt project structure."""
    project_dir = temp_dir / "dbt"
    project_dir.mkdir()
    
    # Create dbt_project.yml
    dbt_project = project_dir / "dbt_project.yml"
    dbt_project.write_text("""
name: test_project
version: 1.0.0
profile: test_profile
model-paths: ["models"]
""")
    
    # Create profiles.yml
    profiles = project_dir / "profiles.yml"
    profiles.write_text("""
test_profile:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: test.duckdb
""")
    
    # Create models directory
    models_dir = project_dir / "models"
    models_dir.mkdir()
    
    return project_dir


@pytest.fixture
def mock_manifest():
    """Create a mock dbt manifest structure."""
    return {
        "metadata": {
            "dbt_version": "1.7.0",
            "generated_at": "2024-01-01T00:00:00.000000Z"
        },
        "nodes": {},
        "sources": {},
        "macros": {},
        "parent_map": {},
        "child_map": {}
    }


@pytest.fixture
def mock_state_dir(temp_dir, mock_manifest):
    """Create a mock state directory with manifest.json."""
    state_dir = temp_dir / ".dbtstate"
    state_dir.mkdir()
    
    import json
    manifest_file = state_dir / "manifest.json"
    manifest_file.write_text(json.dumps(mock_manifest, indent=2))
    
    return state_dir


@pytest.fixture
def mock_runner_config():
    """Create a mock RunnerConfig dictionary for testing."""
    return {
        'dbt_project_dir': '/dbt',
        'profiles_dir': '/dbt',
        'reference_state': '/dbt/.dbtstate',
        'docker_env': [],
        'docker_volumes': [],
        'runner': 'docker',
        'docker_image': 'ghcr.io/dbt-labs/dbt-core:latest'
    }
