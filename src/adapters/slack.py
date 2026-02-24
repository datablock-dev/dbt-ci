"""Slack adapter for dbt CI notifications."""
from argparse import Namespace
from slack_sdk.webhook import WebhookClient

class SlackClient:
    """Wrapper around Slack WebhookClient for sending notifications."""

    def __init__(self, args: Namespace):
        self.args = args
        self.slack_webhook_url = args.slack_webhook
        
        if not self.slack_webhook_url:
            print("Slack webhook URL not provided in args or environment variables.")
            self.webhook_client = None
        else:
            self.webhook_client = WebhookClient(self.slack_webhook_url)

    def send_message(self, header: str, message: str) -> None:
        """Send a message to Slack."""
        if self.webhook_client is None:
            return
        
        payload = {
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": header
                    },
                } if header else None,
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": message
                    },
                },
            ]
        }

        response = self.webhook_client.send_dict(payload)

        if response.status_code != 200:
            raise Exception(f"Failed to send message to Slack: {response.status_code} - {response.body}")