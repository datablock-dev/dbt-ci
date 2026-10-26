"""Unit tests for the ephemeral create/destroy command group."""

import os
from argparse import Namespace
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from dbt_ci.commands.ephemeral.destroy import destroy
from dbt_ci.main import cli


@pytest.fixture(autouse=True)
def clean_env(tmp_path, monkeypatch):
    """Run without a config file or DBT_ variables leaking in from the shell."""
    monkeypatch.chdir(tmp_path)
    for key in list(os.environ):
        if key.startswith("DBT_"):
            monkeypatch.delenv(key, raising=False)


def invoke(*cli_args):
    """Invoke dbt-ci with the create and destroy implementations stubbed out."""
    with (
        patch("dbt_ci.commands.ephemeral.cli.ephemeral") as mock_create,
        patch("dbt_ci.commands.ephemeral.cli.destroy") as mock_destroy,
        patch("dbt_ci.commands.ephemeral.cli.CacheManager"),
    ):
        result = CliRunner().invoke(cli, ["ephemeral", *cli_args])
    return result, mock_create, mock_destroy


class TestEphemeralGroup:
    """Test which implementation each form of the command reaches."""

    def test_bare_command_still_creates(self):
        """'dbt-ci ephemeral --target ci', as existing CI calls it, keeps creating the environment."""
        result, mock_create, mock_destroy = invoke("--target", "ci", "--vars", "{'a': 1}")
        assert result.exit_code == 0, result.output
        mock_create.assert_called_once()
        mock_destroy.assert_not_called()
        args = mock_create.call_args[0][0]
        assert args.target == "ci"
        assert args.vars == "{'a': 1}"

    def test_create_subcommand(self):
        """'ephemeral create' creates the environment with its own options."""
        result, mock_create, mock_destroy = invoke("create", "--target", "ci")
        assert result.exit_code == 0, result.output
        mock_create.assert_called_once()
        mock_destroy.assert_not_called()
        assert mock_create.call_args[0][0].target == "ci"

    def test_destroy_subcommand(self):
        """'ephemeral destroy' tears the environment down and creates nothing."""
        result, mock_create, mock_destroy = invoke("destroy", "--target", "ci", "--dry-run")
        assert result.exit_code == 0, result.output
        mock_create.assert_not_called()
        mock_destroy.assert_called_once()
        args = mock_destroy.call_args[0][0]
        assert args.target == "ci"
        assert args.dry_run is True

    def test_options_before_subcommand_are_rejected(self):
        """An option given before the subcommand would be silently dropped, so it is an error."""
        result, mock_create, mock_destroy = invoke("--target", "ci", "destroy")
        assert result.exit_code == 2
        assert "Pass --target after the subcommand" in result.output
        mock_create.assert_not_called()
        mock_destroy.assert_not_called()

    def test_deprecated_keep_env_is_still_accepted(self):
        """--keep-env keeps parsing so existing pipelines don't break."""
        result, mock_create, _ = invoke("--keep-env")
        assert result.exit_code == 0, result.output
        mock_create.assert_called_once()


class TestDestroy:
    """Test the destroy entry point around the shared teardown."""

    def run_destroy(self, cleanup_side_effect=None):
        """Run destroy with the teardown stubbed, returning the exit code and the mocks."""
        with (
            patch(
                "dbt_ci.commands.ephemeral.destroy.clean_up_ephemeral",
                side_effect=cleanup_side_effect,
            ) as mock_cleanup,
            patch("dbt_ci.commands.ephemeral.destroy.CacheManager") as mock_cm,
            patch("dbt_ci.commands.ephemeral.destroy.apply_cached_config") as mock_apply,
            patch("dbt_ci.commands.ephemeral.destroy.print_exception"),
            patch("dbt_ci.commands.ephemeral.destroy.click.secho"),
            pytest.raises(SystemExit) as exc_info,
        ):
            destroy(Namespace(target=None, dry_run=False))
        return exc_info.value.code, mock_cleanup, mock_cm.return_value, mock_apply

    def test_success_keeps_the_cache(self):
        """A successful teardown exits 0 and leaves the cache for later steps such as finalize."""
        code, mock_cleanup, cache, mock_apply = self.run_destroy()
        assert code == 0
        mock_apply.assert_called_once()
        mock_cleanup.assert_called_once()
        cache.clear_cache.assert_not_called()

    def test_failure_exits_non_zero(self):
        """A failed teardown fails the step."""
        code, _, cache, _ = self.run_destroy(cleanup_side_effect=RuntimeError("boom"))
        assert code == 1
        cache.clear_cache.assert_not_called()


class TestFinalizeCleanEphemeralDeprecation:
    """finalize --clean-ephemeral keeps working but points to the new command."""

    def test_warns_and_still_cleans_up(self):
        """The flag still reaches finalize, with a deprecation warning."""
        with (
            patch("dbt_ci.commands.finalize.cli.finalize") as mock_finalize,
            patch("dbt_ci.commands.finalize.cli.CacheManager"),
            patch("dbt_ci.commands.finalize.cli.logger") as mock_logger,
        ):
            result = CliRunner().invoke(cli, ["finalize", "--clean-ephemeral"])
        assert result.exit_code == 0, result.output
        assert mock_finalize.call_args[0][0].clean_ephemeral is True
        assert "ephemeral destroy" in mock_logger.warning.call_args[0][0]

    def test_no_warning_without_the_flag(self):
        """Plain finalize stays quiet."""
        with (
            patch("dbt_ci.commands.finalize.cli.finalize"),
            patch("dbt_ci.commands.finalize.cli.CacheManager"),
            patch("dbt_ci.commands.finalize.cli.logger") as mock_logger,
        ):
            CliRunner().invoke(cli, ["finalize"])
        mock_logger.warning.assert_not_called()
