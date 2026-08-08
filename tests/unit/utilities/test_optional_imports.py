"""Unit tests for optional dependency handling."""
import pytest

from dbt_ci.utilities.optional_imports import require


class TestRequire:
    """Test the guard used where an optional extra is needed."""

    def test_returns_the_dependency_when_present(self):
        """An installed dependency is passed straight through."""
        module = object()
        assert require(module, "gcp", "The BigQuery connector") is module

    def test_names_the_extra_and_the_install_command(self):
        """The error has to tell the user exactly how to fix it."""
        with pytest.raises(ImportError) as exc:
            require(None, "gcp", "The BigQuery connector")

        message = str(exc.value)
        assert "The BigQuery connector" in message
        assert "'gcp' extra" in message
        assert "pip install 'dbt-ci[gcp]'" in message

    def test_falsy_but_present_dependency_is_returned(self):
        """Only None means missing; a falsy module object is still usable."""

        class Empty:
            """A module-like object that is falsy."""

            def __bool__(self):
                return False

        module = Empty()
        assert require(module, "aws", "S3 state storage") is module
