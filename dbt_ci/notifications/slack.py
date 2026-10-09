"""Slack adapter for dbt CI notifications."""
import logging
from argparse import Namespace
from typing import Any
from slack_sdk.webhook import WebhookClient

logger = logging.getLogger(__name__)

# Slack rejects a section block whose text is longer than this
SLACK_SECTION_TEXT_LIMIT = 3000

class SlackClient:
    """Wrapper around Slack WebhookClient for sending notifications."""

    def __init__(self, args: Namespace):
        self.args = args
        self.slack_webhook_url = getattr(args, 'slack_webhook', None)
        
        if not self.slack_webhook_url:
            logger.debug("Slack webhook URL not provided in args or environment variables.")
            self.webhook_client = None
        else:
            self.webhook_client = WebhookClient(self.slack_webhook_url)

    def send_message(self, header: str, message: str) -> None:
        """Send a message to Slack, truncating each block to Slack's text limit."""
        texts = [text for text in (header, message) if text]
        self.send_blocks([
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": truncate_for_slack(text)
                },
            }
            for text in texts
        ])

    def send_blocks(self, blocks: list[dict[str, Any]], text: str | None = None) -> None:
        """
        Send Block Kit blocks to Slack.

        `text` is the plain-text fallback Slack shows in notifications and in clients
        that cannot render blocks.
        """
        if self.webhook_client is None:
            return

        payload: dict[str, Any] = {"blocks": blocks}
        if text:
            payload["text"] = text

        response = self.webhook_client.send_dict(payload)

        if response.status_code != 200:
            raise Exception(f"Failed to send message to Slack: {response.status_code} - {response.body}")

def truncate_for_slack(text: str, limit: int = SLACK_SECTION_TEXT_LIMIT) -> str:
    """Cut text to Slack's section limit on a line boundary, noting how many lines were left out."""
    if len(text) <= limit:
        return text
    lines = text.splitlines()
    kept: list[str] = []
    # Reserve room for the "...and N more lines" note
    budget = limit - 40
    for line in lines:
        if len("\n".join([*kept, line])) > budget:
            break
        kept.append(line)
    return "\n".join(kept) + f"\n…and {len(lines) - len(kept)} more line(s)"
