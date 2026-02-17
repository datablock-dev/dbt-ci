"""Slack adapter for dbt CI notifications."""
import os
from argparse import Namespace
from slack_sdk.webhook import WebhookClient

def slack_client(args: Namespace) -> WebhookClient | None:
    """Initialize Slack client using configuration from args."""
    slack_webhook_url = None

    if args.slack_webhook:
        slack_webhook_url = args.slack_webhook
    elif os.getenv("SLACK_WEBHOOK_URL"):
        slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    elif os.getenv("SLACK_WEBHOOK"):
        slack_webhook_url = os.getenv("SLACK_WEBHOOK")

    if slack_webhook_url:
        return WebhookClient(slack_webhook_url)
    return None