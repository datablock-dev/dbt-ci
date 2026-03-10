"""Example unit tests for dbt-ci utilities."""
import pytest
from dbt_ci.utilities.paths import get_manifest_file, get_reference_manifest_file


class TestPathUtilities:
    """Test path utility functions."""
    
    def test_get_manifest_file_not_found(self):
        """Test that get_manifest_file raises FileNotFoundError for non-existent path."""
        with pytest.raises(FileNotFoundError) as exc_info:
            get_manifest_file("/nonexistent/path")
        
        assert "manifest.json not found" in str(exc_info.value)
    
    def test_get_reference_manifest_file_not_found(self):
        """Test that get_reference_manifest_file raises FileNotFoundError for non-existent path."""
        with pytest.raises(FileNotFoundError) as exc_info:
            get_reference_manifest_file("/nonexistent/path")
        
        assert "manifest.json not found" in str(exc_info.value)


# Add more test classes for other utilities:
# - test_getters.py
# - test_multi_threading.py
# etc.
