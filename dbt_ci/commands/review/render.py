"""Render the AI review's findings as markdown, for the review command and the report."""

from typing import Any

from dbt_ci.commands.review.claude import SEVERITIES

REVIEW_FILE = "review.json"
SEVERITY_ICONS = {"high": "🔴", "medium": "🟠", "low": "🔵"}


def render_review(review: dict[str, Any] | None, heading: str = "### AI review") -> list[str]:
    """Return the markdown lines of a review, or nothing when there was none."""
    if not review:
        return []
    lines = [heading, ""]
    names: dict[str, str] = review.get("models") or {}
    findings = sorted(
        review.get("findings") or [],
        key=lambda f: SEVERITIES.index(f["severity"]) if f.get("severity") in SEVERITIES else 9,
    )

    if review.get("skipped_reason"):
        lines += [f"Not run: {review['skipped_reason']}.", ""]
        return lines
    for summary in review.get("summaries") or []:
        lines += [summary, ""]
    if not findings and names:
        lines += ["No findings.", ""]
    for finding in findings:
        model = finding.get("model", "?")
        icon = SEVERITY_ICONS.get(finding.get("severity", ""), "•")
        lines.append(
            f"- {icon} **{finding.get('severity', '?')}** · `{names.get(model, model)}` · "
            f"{finding.get('category', '')}: **{finding.get('title', '')}**"
        )
        lines.append(indented(str(finding.get("detail", ""))))
        if finding.get("suggestion"):
            lines.append(indented(f"*Suggestion:* {finding['suggestion']}"))
    if findings:
        lines.append("")

    footer = f"Reviewed {len(names)} model(s) with `{review.get('model', '?')}`"
    if review.get("skipped"):
        footer += f"; {len(review['skipped'])} left out"
    if review.get("errors"):
        footer += f"; {len(review['errors'])} batch(es) failed"
    lines += [f"<sub>{footer}. AI suggestions are advisory: check them before acting.</sub>", ""]
    return lines


def indented(text: str) -> str:
    """Indent every line so multi-line text, code blocks included, stays in its list item."""
    return "\n".join(f"  {line}" if line.strip() else "" for line in text.strip().splitlines())
