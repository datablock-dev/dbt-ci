"""Unit tests for Slack notifications."""
from argparse import Namespace
from unittest.mock import MagicMock, patch

import json
import re

import pytest

from dbt_ci.notifications.slack import SLACK_SECTION_TEXT_LIMIT, SlackClient, truncate_for_slack
from dbt_ci.notifications.slack_summary import build_init_summary_message


def _summary(count: int) -> dict:
    """Build a state change summary with `count` modified models carrying compiled SQL."""
    models = {
        f"model.pkg.m{i}": {"id": f"model.pkg.m{i}", "name": f"m{i}", "resource_type": "model", "compiled_code": "select 1 " * 500}
        for i in range(count)
    }
    return {"modified_nodes": {"model": models}, "new_nodes": None, "deleted_nodes": None}


def _texts(blocks: list[dict]) -> str:
    """Join every mrkdwn text in a block list, including section fields and context elements."""
    texts = []
    for block in blocks:
        texts.append((block.get("text") or {}).get("text", ""))
        texts.extend(field["text"] for field in block.get("fields", []))
        texts.extend(element["text"] for element in block.get("elements", []))
    return "\n".join(texts)


@pytest.fixture(autouse=True)
def no_ci_environment(monkeypatch):
    """Keep the runner's own GitHub Actions variables out of the message."""
    for key in ("GITHUB_REPOSITORY", "GITHUB_HEAD_REF", "GITHUB_REF_NAME", "GITHUB_RUN_ID", "GITHUB_SERVER_URL"):
        monkeypatch.delenv(key, raising=False)


class TestSlackMessage:
    """Test the layout of the init summary sent to Slack."""

    def test_summary_lists_names_not_node_data(self):
        """Compiled SQL and configs are left out; counts and names remain."""
        blocks, _ = build_init_summary_message(_summary(1), Namespace())
        text = _texts(blocks)
        assert "*Modified*\n1" in text
        assert "• `m0` _model_" in text
        assert "select 1" not in text

    def test_starts_with_a_header_block(self):
        """The message opens with a Block Kit header instead of run-on mrkdwn text."""
        blocks, fallback = build_init_summary_message(_summary(1), Namespace())
        assert blocks[0]["type"] == "header"
        assert fallback == "dbt CI: State Change Summary (1 modified, 0 new, 0 deleted)"

    @pytest.mark.parametrize("notifications_format", ["default", "compact", "json"])
    def test_no_emojis(self, notifications_format, monkeypatch):
        """No layout uses emoji shortcodes, including the GitHub Actions context line."""
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
        monkeypatch.setenv("GITHUB_RUN_ID", "42")
        blocks, _ = build_init_summary_message(_summary(1), Namespace(notifications_format=notifications_format))
        text = _texts(blocks)
        assert not re.search(r":[a-z0-9_+-]+:", text.replace("https:", "")), text

    def test_empty_change_set_says_so(self):
        """No changes produce a clear note rather than null values."""
        empty = {"modified_nodes": None, "new_nodes": None, "deleted_nodes": None}
        blocks, _ = build_init_summary_message(empty, Namespace())
        text = _texts(blocks)
        assert "No changes detected" in text
        assert "null" not in text

    def test_compact_format_sends_only_counts(self):
        """The compact layout keeps the counts and drops the node list."""
        blocks, _ = build_init_summary_message(_summary(2), Namespace(notifications_format="compact"))
        text = _texts(blocks)
        assert "*Modified*\n2" in text
        assert "m0" not in text

    def test_json_format_sends_unique_ids_in_a_code_block(self):
        """The json layout sends unique_ids per change type as a fenced JSON block."""
        blocks, _ = build_init_summary_message(_summary(1), Namespace(notifications_format="json"))
        code = blocks[-1]["text"]["text"]
        assert code.startswith("```") and code.endswith("```")
        assert json.loads(code.strip("`")) == {
            "modified_nodes": ["model.pkg.m0"], "new_nodes": [], "deleted_nodes": []
        }

    @pytest.mark.parametrize("notifications_format", ["default", "json"])
    def test_long_messages_stay_within_the_block_limit(self, notifications_format):
        """Large change sets are cut on a line boundary with a note, keeping the code fence."""
        blocks, _ = build_init_summary_message(_summary(500), Namespace(notifications_format=notifications_format))
        text = blocks[-1]["text"]["text"]
        assert len(text) <= SLACK_SECTION_TEXT_LIMIT
        assert "more line(s)" in text
        if notifications_format == "json":
            assert text.endswith("```")

    def test_node_names_are_escaped(self):
        """Characters Slack treats as markup are escaped in node names."""
        summary = {"modified_nodes": {"model": {"model.p.a": {"id": "model.p.a", "name": "a<b>&c", "resource_type": "model"}}}}
        blocks, _ = build_init_summary_message(summary, Namespace())
        assert "a&lt;b&gt;&amp;c" in _texts(blocks)

    def test_github_actions_context(self, monkeypatch):
        """Repository, branch, run link and strategy are shown when running in GitHub Actions."""
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
        monkeypatch.setenv("GITHUB_HEAD_REF", "feat/x")
        monkeypatch.setenv("GITHUB_RUN_ID", "42")
        blocks, _ = build_init_summary_message(_summary(1), Namespace(comparison_strategy="hybrid"))
        context = blocks[1]
        assert context["type"] == "context"
        text = context["elements"][0]["text"]
        assert "<https://github.com/org/repo|org/repo>" in text
        assert "`feat/x`" in text
        assert "<https://github.com/org/repo/actions/runs/42|CI run>" in text
        assert "hybrid comparison" in text

    def test_no_empty_block_without_a_header(self):
        """An empty header no longer produces a null block, which Slack rejects."""
        with patch("dbt_ci.notifications.slack.WebhookClient") as mock_client:
            mock_client.return_value.send_dict.return_value = MagicMock(status_code=200)
            SlackClient(Namespace(slack_webhook="https://hooks.example/x")).send_message("", "body")
        blocks = mock_client.return_value.send_dict.call_args[0][0]["blocks"]
        assert blocks == [{"type": "section", "text": {"type": "mrkdwn", "text": "body"}}]

    def test_send_blocks_includes_fallback_text(self):
        """Blocks are sent as given, with the plain-text fallback for notifications."""
        with patch("dbt_ci.notifications.slack.WebhookClient") as mock_client:
            mock_client.return_value.send_dict.return_value = MagicMock(status_code=200)
            blocks = [{"type": "divider"}]
            SlackClient(Namespace(slack_webhook="https://hooks.example/x")).send_blocks(blocks, "fallback")
        assert mock_client.return_value.send_dict.call_args[0][0] == {"blocks": blocks, "text": "fallback"}
