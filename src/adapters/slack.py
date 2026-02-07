import os
import json
import sys
from typing import Optional, Dict, List, Any
import requests


def send_slack_message(
    message: str,
    webhook_url: Optional[str] = None,
    blocks: Optional[List[Dict[str, Any]]] = None,
    channel: Optional[str] = None,
    username: Optional[str] = None,
    icon_emoji: Optional[str] = None
) -> bool:
    """
    Send a message to Slack using a webhook URL.
    
    Args:
        message: Plain text message to send (used as fallback if blocks are provided)
        webhook_url: Slack webhook URL. If not provided, reads from SLACK_WEBHOOK env var
        blocks: Optional list of Slack Block Kit blocks for rich formatting
        channel: Optional channel override (e.g., "#general", "@username")
        username: Optional bot username override
        icon_emoji: Optional emoji icon (e.g., ":ghost:")
    
    Returns:
        bool: True if message was sent successfully, False otherwise
    
    Environment Variables:
        SLACK_WEBHOOK: Slack webhook URL (https://hooks.slack.com/services/...)
    
    Example:
        send_slack_message("Hello from dbt-ci!")
        
        send_slack_message(
            message="Modified models detected",
            blocks=[{
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Modified models:*\n• model_1\n• model_2"}
            }]
        )
    """    
    # Get webhook URL from parameter or environment variable
    if webhook_url is None:
        webhook_url = os.environ.get('SLACK_WEBHOOK') or os.environ.get("SLACK_WEBHOOK_URL")
    
    if not webhook_url:
        print("Error: Slack webhook URL not provided. Set SLACK_WEBHOOK or SLACK_WEBHOOK_URL environment variable or pass webhook_url parameter")
        return False
    
    # Build payload
    payload: Dict[str, Any] = {
        "text": message
    }
    
    if blocks:
        payload["blocks"] = blocks
    
    if channel:
        payload["channel"] = channel
    
    if username:
        payload["username"] = username
    
    if icon_emoji:
        payload["icon_emoji"] = icon_emoji
    
    try:
        response = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        if response.status_code == 200:
            return True
        else:
            print(f"Error sending Slack message: HTTP {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"Error sending Slack message: {e}")
        return False


def send_dbt_ci_report(
    modified_nodes: List[str],
    webhook_url: Optional[str] = None,
    project_name: Optional[str] = None,
    branch: Optional[str] = None,
    commit_sha: Optional[str] = None
) -> bool:
    """
    Send a formatted dbt CI report to Slack.
    
    Args:
        modified_nodes: List of modified node names
        webhook_url: Slack webhook URL (optional, reads from env)
        project_name: Name of the dbt project
        branch: Git branch name
        commit_sha: Git commit SHA
    
    Returns:
        bool: True if message was sent successfully
    """
    if not modified_nodes:
        message = "✅ No modified models detected"
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*dbt CI Report*\n\n✅ No modified models detected"
                }
            }
        ]
    else:
        node_list = "\n".join([f"• `{node}`" for node in modified_nodes[:20]])
        if len(modified_nodes) > 20:
            node_list += f"\n... and {len(modified_nodes) - 20} more"
        
        message = f"⚠️ {len(modified_nodes)} modified model(s) detected"
        
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*dbt CI Report*\n\n⚠️ *{len(modified_nodes)} modified model(s) detected*"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Modified Models:*\n{node_list}"
                }
            }
        ]
        
        # Add context if provided
        context_elements = []
        if project_name:
            context_elements.append(f"*Project:* {project_name}")
        if branch:
            context_elements.append(f"*Branch:* {branch}")
        if commit_sha:
            context_elements.append(f"*Commit:* {commit_sha[:7]}")
        
        if context_elements:
            blocks.append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": " | ".join(context_elements)
                }]
            })
    
    return send_slack_message(
        message=message,
        blocks=blocks,
        webhook_url=webhook_url,
        username="dbt CI",
        icon_emoji=":dbt:"
    )
