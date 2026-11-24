"""Unit tests for the warning about a state built by a different dbt version."""

import json
import logging
from pathlib import Path

from dbt_ci.commands.init.version_check import (
    check_state_dbt_version,
    manifest_dbt_version,
    read_state_dbt_version,
    version_mismatch_message,
)
from dbt_ci.commands.report.index import render_dbt_version_warning


def manifest(version: str | None) -> dict:
    """Return a minimal manifest recording the given dbt version."""
    return {"metadata": {"dbt_version": version} if version else {}, "nodes": {}}


def write_state(directory: Path, version: str | None) -> str:
    """Write a state directory holding a manifest built by the given dbt version."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_text(json.dumps(manifest(version)))
    return str(directory)


class TestManifestDbtVersion:
    """Test reading the dbt version from a manifest."""

    def test_reads_the_metadata_version(self):
        """The version comes from metadata.dbt_version."""
        assert manifest_dbt_version(manifest("1.12.7")) == "1.12.7"

    def test_missing_version(self):
        """A manifest without a version, or no manifest at all, has none."""
        assert manifest_dbt_version(manifest(None)) is None
        assert manifest_dbt_version({}) is None
        assert manifest_dbt_version(None) is None

    def test_reads_a_state_directory(self, tmp_path):
        """The state's version is read from its manifest.json."""
        assert read_state_dbt_version(write_state(tmp_path / "state", "1.11.17")) == "1.11.17"

    def test_unreadable_state(self, tmp_path):
        """A missing or broken state is not an error here."""
        assert read_state_dbt_version(None) is None
        assert read_state_dbt_version(str(tmp_path / "missing")) is None
        (tmp_path / "broken").mkdir()
        (tmp_path / "broken" / "manifest.json").write_text("{not json")
        assert read_state_dbt_version(str(tmp_path / "broken")) is None


class TestCheckStateDbtVersion:
    """Test the comparison init runs before resolving the change set."""

    def test_same_version_is_silent(self, tmp_path, caplog):
        """Matching versions return nothing and log nothing."""
        state = write_state(tmp_path / "state", "1.12.7")
        with caplog.at_level(logging.INFO):
            assert check_state_dbt_version(state, manifest("1.12.7"), "hybrid") is None
        assert not caplog.records

    def test_mismatch_warns_for_state_comparison(self, tmp_path, caplog):
        """dbt and hybrid rely on state:modified, so a mismatch is a warning."""
        state = write_state(tmp_path / "state", "1.11.17")
        for strategy in ("dbt", "hybrid"):
            caplog.clear()
            with caplog.at_level(logging.INFO):
                result = check_state_dbt_version(state, manifest("1.12.7"), strategy)
            assert result == {"state": "1.11.17", "current": "1.12.7"}
            assert [r.levelno for r in caplog.records] == [logging.WARNING]
            assert "dbt 1.11.17" in caplog.text and "dbt 1.12.7" in caplog.text

    def test_mismatch_is_only_noted_for_git(self, tmp_path, caplog):
        """The git strategy doesn't use state:modified, so a mismatch is only noted."""
        state = write_state(tmp_path / "state", "1.12.6")
        with caplog.at_level(logging.INFO):
            result = check_state_dbt_version(state, manifest("2.0.12"), "git")
        assert result == {"state": "1.12.6", "current": "2.0.12"}
        assert [r.levelno for r in caplog.records] == [logging.INFO]

    def test_unknown_versions_are_not_a_mismatch(self, tmp_path):
        """Without both versions there is nothing to compare."""
        state = write_state(tmp_path / "state", None)
        assert check_state_dbt_version(state, manifest("1.12.7"), "dbt") is None
        state = write_state(tmp_path / "other", "1.12.7")
        assert check_state_dbt_version(state, manifest(None), "dbt") is None
        assert check_state_dbt_version(None, manifest("1.12.7"), "dbt") is None

    def test_message_suggests_a_fix_only_for_state_comparison(self):
        """The advice to rebuild the state or switch strategy only applies to dbt and hybrid."""
        assert "--comparison-strategy git" in version_mismatch_message("1.11.0", "1.12.0", "dbt")
        assert "state:modified" not in version_mismatch_message("1.11.0", "1.12.0", "git")


class TestRenderDbtVersionWarning:
    """Test the report's warning about mismatched dbt versions."""

    def test_renders_when_init_recorded_a_mismatch(self):
        """The report names both versions."""
        lines = render_dbt_version_warning(
            {"init": {"dbt_versions": {"state": "1.11.17", "current": "1.12.7"}}}
        )
        assert "dbt 1.11.17" in lines[0] and "dbt 1.12.7" in lines[0]

    def test_renders_nothing_otherwise(self):
        """Matching versions and older reports render nothing."""
        assert render_dbt_version_warning(None) == []
        assert render_dbt_version_warning({"init": {}}) == []
        assert render_dbt_version_warning({"init": {"dbt_versions": {"state": "1.0"}}}) == []
