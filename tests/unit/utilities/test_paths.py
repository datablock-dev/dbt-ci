"""Tests for locating the dbt project, its profiles.yml and the target's output."""

from argparse import Namespace

import pytest

from dbt_ci.errors import ConfigurationError
from dbt_ci.utilities.paths import get_profile, get_profiles_file

PROFILES_YML = """
demo:
  target: dev
  outputs:
    dev:
      type: duckdb
      threads: 1
    prod:
      type: duckdb
      threads: 8
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A dbt project without a profiles.yml, run from an unrelated directory with an empty home."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "dbt_project.yml").write_text("name: demo\nprofile: demo\n")
    home = tmp_path / "home"
    home.mkdir()
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(workdir)
    return project_dir


def args_for(project_dir, **overrides) -> Namespace:
    """Build the arguments get_profile reads."""
    return Namespace(
        **{"dbt_project_dir": str(project_dir), "profiles_dir": None, "target": None, **overrides}
    )


class TestGetProfile:
    """get_profile finds profiles.yml wherever dbt would."""

    def test_profiles_dir(self, project, tmp_path):
        """An explicit --profiles-dir outside the project is honoured."""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "profiles.yml").write_text(PROFILES_YML)

        assert get_profile(args_for(project, profiles_dir=str(profiles_dir)))["type"] == "duckdb"

    def test_project_dir(self, project):
        """profiles.yml next to dbt_project.yml is found without --profiles-dir."""
        (project / "profiles.yml").write_text(PROFILES_YML)
        assert get_profile(args_for(project))["threads"] == 1

    def test_working_directory(self, project, tmp_path):
        """dbt's own default: profiles.yml in the working directory."""
        (tmp_path / "workdir" / "profiles.yml").write_text(PROFILES_YML)
        assert get_profile(args_for(project))["threads"] == 1

    def test_home_dbt_dir(self, project, tmp_path):
        """dbt's own default: ~/.dbt/profiles.yml."""
        (tmp_path / "home" / ".dbt").mkdir()
        (tmp_path / "home" / ".dbt" / "profiles.yml").write_text(PROFILES_YML)
        assert get_profile(args_for(project))["threads"] == 1

    def test_explicit_target_wins_over_the_default(self, project):
        """--target selects its output; otherwise the profile's default target is used."""
        (project / "profiles.yml").write_text(PROFILES_YML)
        assert get_profile(args_for(project, target="prod"))["threads"] == 8

    def test_missing_profiles_yml(self, project):
        """No profiles.yml anywhere is a configuration error naming where it looked."""
        with pytest.raises(ConfigurationError, match="profiles.yml not found in .*project"):
            get_profile(args_for(project))

    def test_profiles_dir_is_the_only_place_searched(self, project, tmp_path):
        """With --profiles-dir set, a profiles.yml elsewhere is not picked up instead."""
        (project / "profiles.yml").write_text(PROFILES_YML)
        with pytest.raises(ConfigurationError, match="profiles.yml not found in .*nowhere"):
            get_profiles_file(str(project), str(tmp_path / "nowhere"))

    def test_unknown_target(self, project):
        """A target the profile does not define is reported by name."""
        (project / "profiles.yml").write_text(PROFILES_YML)
        with pytest.raises(
            ConfigurationError, match="Target 'staging' not found in profile 'demo'"
        ):
            get_profile(args_for(project, target="staging"))

    def test_unknown_profile(self, project):
        """A profile name dbt_project.yml refers to must exist in profiles.yml."""
        (project / "dbt_project.yml").write_text("name: demo\nprofile: other\n")
        (project / "profiles.yml").write_text(PROFILES_YML)
        with pytest.raises(ConfigurationError, match="Profile 'other' not found"):
            get_profile(args_for(project))
