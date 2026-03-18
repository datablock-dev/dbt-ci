"""Unit tests for the config command."""
import pytest
from unittest.mock import patch, mock_open
from dbt_ci.commands.config.index import generate_config, SKELETON


class TestGenerateConfig:
    """Test the generate_config function."""

    def test_creates_file_with_skeleton_content(self, tmp_path):
        """Test that a new config file is created with the skeleton content."""
        output = str(tmp_path / "dbt-ci.config.yaml")
        generate_config(output=output, force=False)

        with open(output, "r", encoding="utf-8") as f:
            content = f.read()

        assert content == SKELETON

    def test_exits_if_file_exists_without_force(self, tmp_path):
        """Test that the command exits if the file already exists and --force is not set."""
        output = tmp_path / "dbt-ci.config.yaml"
        output.write_text("existing content")

        with pytest.raises(SystemExit) as exc_info:
            generate_config(output=str(output), force=False)

        assert exc_info.value.code == 1
        # Existing file must not be overwritten
        assert output.read_text() == "existing content"

    def test_overwrites_if_force(self, tmp_path):
        """Test that --force overwrites an existing file."""
        output = tmp_path / "dbt-ci.config.yaml"
        output.write_text("old content")

        generate_config(output=str(output), force=True)

        assert output.read_text() == SKELETON

    def test_skeleton_contains_schema_comment(self):
        """Test that the skeleton includes the yaml-language-server schema comment."""
        assert "yaml-language-server" in SKELETON
        assert "dbt-ci.config.schema.json" in SKELETON

    def test_skeleton_contains_required_sections(self):
        """Test that the skeleton covers all major config sections."""
        for section in ("project-dir", "runner", "init:", "finalize:", "docker:"):
            assert section in SKELETON, f"Missing section: {section}"
