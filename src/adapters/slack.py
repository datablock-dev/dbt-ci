"""Slack adapter for dbt CI notifications."""
from argparse import Namespace

def slack_client(variables: Namespace):
    """Initialize Slack client using configuration from variables."""
    webhook_url = variables.variables.slack_webhook
    if not webhook_url:
        print("Warning: No Slack webhook URL provided. Slack notifications will be disabled.")
        return None
    return {
        "webhook_url": webhook_url
    }