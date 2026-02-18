"""Example unit tests for dbt-ci utilities."""
import pytest
from src.utilities.paths import get_manifest_file, get_reference_manifest_file


class TestPathUtilities:
    """Test path utility functions."""
    
    def test_get_manifest_file_not_found(self, capsys):
        """Test that get_manifest_file exits with error for non-existent path."""
        with pytest.raises(SystemExit) as exc_info:
            get_manifest_file("/nonexistent/path")
        
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "manifest.json not found" in captured.out
    
    def test_get_reference_manifest_file_not_found(self, capsys):
        """Test that get_reference_manifest_file exits with error for non-existent path."""
        with pytest.raises(SystemExit) as exc_info:
            get_reference_manifest_file("/nonexistent/path")
        
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "manifest.json not found" in captured.out


# Add more test classes for other utilities:
# - test_getters.py
# - test_multi_threading.py
# etc.
