"""pytest configuration and shared fixtures for dbt-ci tests."""
import pytest
import tempfile
import shutil
from pathlib import Path


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
