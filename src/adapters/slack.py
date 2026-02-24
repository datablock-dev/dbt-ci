"""Slack adapter for dbt CI notifications."""
import os
from argparse import Namespace
from slack_sdk.webhook import WebhookClient

class SlackClient:
    """Wrapper around Slack WebhookClient for sending notifications."""

    def __init__(self, args: Namespace):
        self.args = args
        self.slack_webhook_url = args.slack_webhook
        
        if not self.slack_webhook_url:
            raise ValueError("Slack webhook URL not provided in args or environment variables.")
        
        self.webhook_client = WebhookClient(self.slack_webhook_url)

    def send_message(self, message: str) -> None:
        """Send a message to Slack."""
        response = self.webhook_client.send(text=message)
        if response.status_code != 200:
            raise Exception(f"Failed to send message to Slack: {response.status_code} - {response.body}")