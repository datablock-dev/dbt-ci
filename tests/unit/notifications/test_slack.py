"""Unit tests for Slack notifications."""
from argparse import Namespace
from unittest.mock import MagicMock, patch

from dbt_ci.commands.init.index import format_slack_summary
from dbt_ci.notifications.slack import SLACK_SECTION_TEXT_LIMIT, SlackClient, truncate_for_slack


def _summary(count: int) -> dict:
    """Build a state change summary with `count` modified models carrying compiled SQL."""
    models = {
        f"model.pkg.m{i}": {"name": f"m{i}", "resource_type": "model", "compiled_code": "select 1 " * 500}
        for i in range(count)
    }
    return {"modified_nodes": {"model": models}, "new_nodes": None, "deleted_nodes": None}


class TestSlackMessage:
    """Test that the init summary fits in a Slack message."""

    def test_summary_lists_names_not_node_data(self):
        """Compiled SQL and configs are left out; counts and names remain."""
        text = format_slack_summary(_summary(1))
        assert "Modified Nodes: 1" in text
        assert "• m0 [model]" in text
        assert "select 1" not in text

    def test_long_messages_are_truncated(self):
        """Large change sets are cut on a line boundary with a note."""
        text = truncate_for_slack(format_slack_summary(_summary(500)))
        assert len(text) <= SLACK_SECTION_TEXT_LIMIT
        assert text.endswith("more line(s)")

    def test_no_empty_block_without_a_header(self):
        """An empty header no longer produces a null block, which Slack rejects."""
        with patch("dbt_ci.notifications.slack.WebhookClient") as mock_client:
            mock_client.return_value.send_dict.return_value = MagicMock(status_code=200)
            SlackClient(Namespace(slack_webhook="https://hooks.example/x")).send_message("", "body")
        blocks = mock_client.return_value.send_dict.call_args[0][0]["blocks"]
        assert blocks == [{"type": "section", "text": {"type": "mrkdwn", "text": "body"}}]
