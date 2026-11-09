"""
Plain-language reasons for why init counted a node as modified, new or deleted.

Reviewers' most common question about a CI run is "why is this model in my PR?". Each
comparison strategy records the evidence it used, such as the changed file, the changed
macro or the difference from the reference manifest, so `run` and `report` can show it.
"""

from dbt_ci.graph.graph_utils import get_node
from dbt_ci.schema import DependencyGraph, DependencyGraphNode, StateChangeSummary
from dbt_ci.utilities.git import GitChangeType

# How a git change type reads after a file path
FILE_VERBS: dict[GitChangeType, str] = {
    "modified": "changed",
    "added": "added",
    "deleted": "deleted",
}

# Config keys listed by name before the rest are summarised as "and N more"
MAX_CONFIG_KEYS = 3


class ChangeReasons:
    """Collect the reasons for each node, keyed by unique_id, without duplicates."""

    def __init__(self) -> None:
        """Start with no reasons."""
        self.by_node: dict[str, list[str]] = {}

    def add(self, node_id: str, reason: str) -> None:
        """Record a reason for a node, once."""
        reasons = self.by_node.setdefault(node_id, [])
        if reason not in reasons:
            reasons.append(reason)

    def for_summary(
        self,
        summary: StateChangeSummary,
        reference_graph: DependencyGraph,
        target_graph: DependencyGraph,
    ) -> dict[str, list[str]]:
        """
        Return the reasons for exactly the nodes in a change set.

        Nodes that no strategy-specific evidence explained, such as ones only dbt's state
        comparison flagged, get a reason derived from the two manifests instead, so every
        node in the change set has at least one.
        """
        result: dict[str, list[str]] = {}
        for change_key in ("modified_nodes", "new_nodes", "deleted_nodes"):
            for nodes in (summary.get(change_key) or {}).values():  # type: ignore[attr-defined]
                for node_id in nodes:
                    result[node_id] = self.by_node.get(node_id) or compare_with_reference(
                        node_id, change_key, reference_graph, target_graph
                    )
        return result


def file_reason(change_type: GitChangeType, path: str, node: DependencyGraphNode) -> str:
    """Describe a changed file as the reason for a node defined or configured in it."""
    verb = FILE_VERBS[change_type]
    if node.get("original_file_path") != path and node.get("patch_path") == path:
        if change_type == "modified":
            return f"properties in `{path}` changed"
        return f"properties file `{path}` {verb}"
    return f"`{path}` {verb}"


def macro_reason(macro_id: str) -> str:
    """Describe a changed macro as the reason for a node that uses it."""
    return f"uses changed macro `{macro_id.split('.')[-1]}`"


def compare_with_reference(
    node_id: str,
    change_key: str,
    reference_graph: DependencyGraph,
    target_graph: DependencyGraph,
) -> list[str]:
    """
    Explain a node's change by comparing it with the reference manifest.

    dbt's state comparison says that a node changed, not why, so the code checksum and
    the config of both versions are compared here to say what differs.
    """
    if change_key == "new_nodes":
        return ["not in the reference manifest"]
    if change_key == "deleted_nodes":
        return ["no longer in the project"]

    reference = get_node(reference_graph, node_id)
    target = get_node(target_graph, node_id)
    reasons: list[str] = []
    if reference is not None and target is not None:
        if code_differs(reference, target):
            reasons.append("code differs from the reference manifest")
        changed_keys = changed_config_keys(reference, target)
        if changed_keys:
            named = ", ".join(f"`{key}`" for key in changed_keys[:MAX_CONFIG_KEYS])
            more = len(changed_keys) - MAX_CONFIG_KEYS
            reasons.append(f"config differs: {named}" + (f" and {more} more" if more > 0 else ""))
    return reasons or ["flagged by dbt's state comparison"]


def code_differs(reference: DependencyGraphNode, target: DependencyGraphNode) -> bool:
    """Report whether two versions of a node have different code, by checksum."""
    before, after = reference.get("checksum"), target.get("checksum")
    return bool(before and after and before != after)


def changed_config_keys(reference: DependencyGraphNode, target: DependencyGraphNode) -> list[str]:
    """Return the config keys whose values differ between two versions of a node."""
    before = reference.get("config") or {}
    after = target.get("config") or {}
    keys = set(before) | set(after)
    return sorted(key for key in keys if before.get(key) != after.get(key))  # type: ignore[misc]


def drift_reason(base_branch: str) -> str:
    """Describe code that differs from the reference although this branch didn't change it."""
    return (
        f"not changed on this branch: `{base_branch}` and the reference manifest differ here "
        "(e.g. merged after this branch was created, or not deployed yet)"
    )
