"""Unit tests for dbt version helpers."""
import pytest

from dbt_ci.dbt.versions import get_dbt_distribution, get_major_version, is_dbt_v2


class TestGetMajorVersion:
    """Test parsing the major version out of a dbt version string."""

    @pytest.mark.parametrize(
        "version, expected",
        [
            ("1.12.5", 1),
            ("2.0.6", 2),
            ("2.0.0rc8", 2),
            ("v2.0.0", 2),
            ("==1.10.13", 1),
            ("latest", None),
            ("", None),
            (None, None),
        ],
    )
    def test_parses_major(self, version, expected):
        """Common spellings resolve to their major version; anything else is unknown."""
        assert get_major_version(version) == expected


class TestDistribution:
    """Test which PyPI distribution provides a dbt version."""

    def test_v1_is_dbt_core(self):
        """dbt 1.x is published as dbt-core."""
        assert not is_dbt_v2("1.12.5")
        assert get_dbt_distribution("1.12.5") == "dbt-core"

    def test_v2_is_dbt(self):
        """dbt v2 is published as dbt."""
        assert is_dbt_v2("2.0.6")
        assert get_dbt_distribution("2.0.6") == "dbt"

    def test_unknown_defaults_to_dbt_core(self):
        """An unparsable version keeps the historical dbt-core behaviour."""
        assert get_dbt_distribution(None) == "dbt-core"
