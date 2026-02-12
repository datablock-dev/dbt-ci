"""Slack adapter for dbt CI notifications."""
import os
from argparse import Namespace
from slack_sdk.webhook import WebhookClient

def slack_client(variables: Namespace) -> WebhookClient | None:
    """Initialize Slack client using configuration from variables."""
    slack_webhook_url = None

    if variables.slack_webhook:
        slack_webhook_url = variables.slack_webhook
    elif os.getenv("SLACK_WEBHOOK_URL"):
        slack_webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    elif os.getenv("SLACK_WEBHOOK"):
        slack_webhook_url = os.getenv("SLACK_WEBHOOK")

    if slack_webhook_url:
        return WebhookClient(slack_webhook_url)
    return None