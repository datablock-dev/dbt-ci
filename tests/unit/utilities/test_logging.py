"""Unit tests for log redaction and log file helpers."""
import logging
from argparse import Namespace

from dbt_ci.utilities.logging import REDACTED, flush_log_file, redact, redact_namespace


class TestRedact:
    """Test masking of secret-looking configuration values."""

    def test_masks_sensitive_keys(self):
        """A key whose name marks it as a secret has its value replaced."""
        assert redact("https://hooks.slack.com/abc", "slack_webhook") == REDACTED

    def test_key_matching_is_case_insensitive(self):
        """Key names are matched regardless of case."""
        assert redact("abc", "API_KEY") == REDACTED

    def test_keeps_ordinary_values(self):
        """Non-sensitive configuration is logged as-is so debugging still works."""
        assert redact("dbt", "runner") == "dbt"

    def test_masks_env_pair_values(self):
        """KEY=VALUE entries keep their name but lose a secret value."""
        assert redact(["DBT_TOKEN=abc", "DBT_TARGET=prod"]) == [
            f"DBT_TOKEN={REDACTED}",
            "DBT_TARGET=prod",
        ]

    def test_recurses_into_mappings(self):
        """Nested structures are walked."""
        result = redact({"environment": {"PASSWORD": "hunter2", "TARGET": "prod"}})
        assert result == {"environment": {"PASSWORD": REDACTED, "TARGET": "prod"}}

    def test_preserves_sequence_type(self):
        """Tuples stay tuples so callers aren't surprised by the redacted copy."""
        assert isinstance(redact(("a", "b")), tuple)

    def test_namespace_is_redacted(self):
        """Command args are masked before being written to the debug log."""
        args = Namespace(runner="dbt", slack_webhook="https://hooks.slack.com/abc")

        result = redact_namespace(args)

        assert result == {"runner": "dbt", "slack_webhook": REDACTED}

    def test_docker_env_credentials_are_masked(self):
        """--docker-env values are the most likely place for credentials to appear."""
        args = Namespace(docker_env=["GOOGLE_TOKEN=xyz", "DBT_PROFILES_DIR=/dbt"])

        result = redact_namespace(args)

        assert result["docker_env"] == [f"GOOGLE_TOKEN={REDACTED}", "DBT_PROFILES_DIR=/dbt"]


class TestFlushLogFile:
    """Test that buffered records can be forced to disk."""

    def test_flushes_file_handlers(self, tmp_path):
        """Records buffered by a FileHandler are written out on demand."""
        log_path = tmp_path / "dbt-ci.log"
        handler = logging.FileHandler(log_path, encoding="utf-8")
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            logging.getLogger("demo").error("recorded")
            flush_log_file()
            assert "recorded" in log_path.read_text(encoding="utf-8")
        finally:
            root.removeHandler(handler)
            handler.close()
