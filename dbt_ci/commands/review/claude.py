"""
Ask Claude to review changed dbt models, and get its findings back as structured data.

The `anthropic` SDK is an optional dependency (`pip install dbt-ci[ai]`). It finds its
credentials itself: ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN or an `ant auth login`
profile. Models are sent in batches; every batch shares the same system prompt, which
is marked for prompt caching.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from dbt_ci.errors import DbtCiError

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"
EFFORTS = ("low", "medium", "high", "xhigh", "max")
SEVERITIES = ("high", "medium", "low")
CATEGORIES = ("performance", "correctness", "testing", "materialization", "maintainability")
# Models per request: enough to share context, few enough to keep each answer focused
BATCH_SIZE = 8
MAX_TOKENS = 16000
# Server-side refusal fallbacks, for the models that accept them
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = (
    "claude-opus-5-5",
    "claude-opus-5",
    "claude-fable-5-2",
    "claude-fable-5-1",
    "claude-sonnet-5-5",
)

SYSTEM_PROMPT = """\
You review dbt models changed in a pull request, the way an experienced analytics \
engineer would before approving it.

For each model you get its SQL (compiled when available), the diff of its source \
against production for modified models, its build config, the tests on it, how many \
models and which exposures (dashboards, applications) depend on it directly, and how \
long it took to build on the last deploy. The warehouse is named when known; tailor \
the advice to it.

Report concrete problems that are worth a reviewer's attention:
- performance and cost: full rebuilds of large tables that could be incremental, \
missing partition or cluster pruning, scanning more columns or rows than needed, \
expensive patterns repeated in a slow model
- correctness: join fan-out, filters that drop or duplicate rows, non-deterministic \
results, incremental logic that misses late or updated rows, wrong unique_key
- testing: primary or unique keys without tests, new models with no tests at all
- materialization: a materialization that does not fit how the model is used
- maintainability: only when it is likely to cause a real problem

Rules:
- Only report a problem you can point to in the code you were given. Do not guess \
about tables or columns you cannot see. No style nits.
- Severity: high = likely wrong results or a large cost; medium = a real problem worth \
fixing in this pull request; low = worth knowing.
- Give each finding a short title, what is wrong and why it matters, and a concrete \
suggestion, with a short SQL or config snippet when it helps.
- Refer to models by their unique_id. An empty list of findings is a good answer.
- In the summary, say in one or two sentences what changed and whether anything \
needs attention before merging."""

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "model": {"type": "string"},
                    "severity": {"type": "string", "enum": list(SEVERITIES)},
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "suggestion": {"type": "string"},
                },
                "required": ["model", "severity", "category", "title", "detail", "suggestion"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "findings"],
    "additionalProperties": False,
}


@dataclass
class ReviewSettings:
    """How to call Claude: the model, the effort and extra instructions from the team."""

    model: str = DEFAULT_MODEL
    effort: str = DEFAULT_EFFORT
    instructions: str | None = None


@dataclass
class ReviewResult:
    """Claude's findings and summaries, the batches that failed, and the tokens used."""

    findings: list[dict[str, Any]] = field(default_factory=list)
    summaries: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    served_by: set[str] = field(default_factory=set)


def make_client() -> Any:
    """Return an Anthropic client, or raise a DbtCiError saying how to install the SDK."""
    try:
        import anthropic
    except ImportError as e:
        raise DbtCiError("dbt-ci review needs the Anthropic SDK: pip install 'dbt-ci[ai]'") from e
    # The SDK logs every HTTP request at INFO, which would interleave with the review
    for name in ("anthropic", "httpx2", "httpx"):
        logging.getLogger(name).setLevel(max(logging.getLogger(name).level, logging.WARNING))
    return anthropic.Anthropic()


def review_models(
    client: Any,
    models: Sequence[dict[str, Any]],
    settings: ReviewSettings,
    adapter: str | None = None,
) -> ReviewResult:
    """Review the models in batches; a failed batch is recorded and the rest carry on."""
    result = ReviewResult()
    system = system_blocks(settings.instructions)
    for start in range(0, len(models), BATCH_SIZE):
        batch = list(models[start : start + BATCH_SIZE])
        names = ", ".join(str(m.get("name")) for m in batch)
        try:
            answer = request_review(client, system, batch, settings, adapter, result)
        except Exception as e:  # One failed batch must not lose the others' findings
            logger.warning(f"The AI review of {names} failed: {e}")
            result.errors.append(f"{names}: {e}")
            continue
        result.findings.extend(answer.get("findings") or [])
        if answer.get("summary"):
            result.summaries.append(answer["summary"])
    return result


def system_blocks(instructions: str | None) -> list[dict[str, Any]]:
    """Return the system prompt, with the team's instructions, marked for caching."""
    text = SYSTEM_PROMPT
    if instructions and instructions.strip():
        text += "\n\nInstructions from the team that owns this project:\n" + instructions.strip()
    # Identical for every batch and every run with the same instructions, so it caches
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def request_review(
    client: Any,
    system: list[dict[str, Any]],
    batch: list[dict[str, Any]],
    settings: ReviewSettings,
    adapter: str | None,
    result: ReviewResult,
) -> dict[str, Any]:
    """Send one batch of models and return Claude's parsed answer."""
    payload = {"warehouse": adapter or "unknown", "models": batch}
    params: dict[str, Any] = {
        "model": settings.model,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "messages": [
            {
                "role": "user",
                "content": "Review these changed dbt models:\n\n"
                + json.dumps(payload, indent=2, sort_keys=True, default=str),
            }
        ],
        "output_config": {
            "effort": settings.effort,
            "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
        },
    }
    if settings.model in FALLBACK_MODELS:
        # If a safety classifier declines, the same request runs on a fallback model
        params["betas"] = [FALLBACK_BETA]
        params["fallbacks"] = "default"
    response = client.beta.messages.create(**params)
    add_usage(result, response)

    if response.stop_reason == "refusal":
        category = (
            getattr(response.stop_details, "category", None) if response.stop_details else None
        )
        raise DbtCiError(f"Claude declined to review this batch ({category or 'no category'})")
    if response.stop_reason == "max_tokens":
        raise DbtCiError("Claude's answer was cut off at the output limit")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise DbtCiError("Claude's answer had no text")
    return json.loads(text)


def add_usage(result: ReviewResult, response: Any) -> None:
    """Add a response's token counts, and the model that answered, to the result."""
    result.served_by.add(str(getattr(response, "model", "") or ""))
    usage = getattr(response, "usage", None)
    for key in (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ):
        value = getattr(usage, key, None)
        if isinstance(value, int):
            result.usage[key] = result.usage.get(key, 0) + value
