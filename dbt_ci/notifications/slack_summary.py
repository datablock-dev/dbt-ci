"""Build the Slack Block Kit message that `init` posts for a state change summary."""
import json
import os
from argparse import Namespace
from typing import Any, Literal, cast
from dbt_ci.schema import StateChangeSummary, StateChangeSummaryKeys
from dbt_ci.notifications.slack import SLACK_SECTION_TEXT_LIMIT, truncate_for_slack

type SlackFormat = Literal["default", "compact", "json"]

SLACK_FORMATS: list[SlackFormat] = ["default", "compact", "json"]

# Display order, label and emoji for each bucket of the change set
CHANGE_TYPES: list[tuple[StateChangeSummaryKeys, str, str]] = [
    ("modified_nodes", "Modified", ":pencil2:"),
    ("new_nodes", "New", ":sparkles:"),
    ("deleted_nodes", "Deleted", ":wastebasket:"),
]


def escape_mrkdwn(text: str) -> str:
    """Escape the characters Slack treats as control sequences in mrkdwn text."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def get_summary_nodes(state_change_summary: StateChangeSummary, key: StateChangeSummaryKeys) -> list[dict]:
    """Flatten one bucket of the change set into nodes sorted by resource type, then name."""
    buckets = state_change_summary.get(key) or {}
    nodes = [node for node_dict in buckets.values() for node in node_dict.values()]
    return sorted(nodes, key=lambda n: (n.get("resource_type") or "", n.get("name") or ""))


def format_node_list(label: str, emoji: str, nodes: list[dict]) -> str:
    """Render one change type as a mrkdwn bullet list of node names and resource types."""
    lines = [f"{emoji} *{label} nodes ({len(nodes)})*"]
    for node in nodes:
        name = escape_mrkdwn(str(node.get("name") or node.get("id") or "unknown"))
        resource_type = escape_mrkdwn(str(node.get("resource_type") or "node"))
        lines.append(f"• `{name}` _{resource_type}_")
    return truncate_for_slack("\n".join(lines))


def format_json_summary(nodes_by_type: dict[StateChangeSummaryKeys, list[dict]]) -> str:
    """Render the change set as a JSON code block of unique_ids per change type."""
    payload = {
        key: [node.get("id") or node.get("name") for node in nodes_by_type[key]]
        for key, _, _ in CHANGE_TYPES
    }
    # Leave room for the code fence so truncation never cuts it off
    body = truncate_for_slack(json.dumps(payload, indent=2), limit=SLACK_SECTION_TEXT_LIMIT - 8)
    return f"```{body}```"


def get_run_context(args: Namespace) -> list[str]:
    """
    Describe where the run came from: repository, branch, CI run link and comparison strategy.

    The CI details come from GitHub Actions' environment and are left out elsewhere.
    """
    context: list[str] = []
    repository = os.environ.get("GITHUB_REPOSITORY")
    server_url = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    branch = os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME")
    run_id = os.environ.get("GITHUB_RUN_ID")

    if repository:
        context.append(f":file_folder: <{server_url}/{repository}|{escape_mrkdwn(repository)}>")
    if branch:
        context.append(f":twisted_rightwards_arrows: `{escape_mrkdwn(branch)}`")
    if repository and run_id:
        context.append(f":gear: <{server_url}/{repository}/actions/runs/{run_id}|CI run>")

    strategy = getattr(args, "comparison_strategy", None)
    if strategy:
        context.append(f":mag: {escape_mrkdwn(str(strategy))} comparison")
    return context


def build_init_summary_message(
    state_change_summary: StateChangeSummary,
    args: Namespace,
) -> tuple[list[dict[str, Any]], str]:
    """
    Build the Block Kit blocks and plain-text fallback for the init summary.

    The layout follows --slack-format: "default" lists each changed node by name,
    "compact" sends only the counts and "json" sends the unique_ids as a code block.
    Full node data (compiled SQL, configs, lineage) is never sent: it exceeds Slack's
    per-block text limit even for a single changed model.
    """
    slack_format = cast(SlackFormat, (getattr(args, "slack_format", None) or "default").lower())
    nodes_by_type = {key: get_summary_nodes(state_change_summary, key) for key, _, _ in CHANGE_TYPES}
    total = sum(len(nodes) for nodes in nodes_by_type.values())

    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": ":bar_chart: dbt CI: State Change Summary", "emoji": True}},
    ]

    context = get_run_context(args)
    if context:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "  |  ".join(context)}]})

    blocks.append({
        "type": "section",
        "fields": [
            {"type": "mrkdwn", "text": f"{emoji} *{label}*\n{len(nodes_by_type[key])}"}
            for key, label, emoji in CHANGE_TYPES
        ],
    })

    if total == 0:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": ":white_check_mark: No changes detected compared to the reference state."},
        })
    elif slack_format == "json":
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": format_json_summary(nodes_by_type)}})
    elif slack_format == "default":
        blocks.append({"type": "divider"})
        for key, label, emoji in CHANGE_TYPES:
            if nodes_by_type[key]:
                blocks.append({
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": format_node_list(label, emoji, nodes_by_type[key])},
                })

    counts = ", ".join(f"{len(nodes_by_type[key])} {label.lower()}" for key, label, _ in CHANGE_TYPES)
    fallback_text = f"dbt CI: State Change Summary ({counts})"
    return blocks, fallback_text
