"""Tests for the AI review of changed models (dbt-ci review)."""

import json
from argparse import Namespace
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from dbt_ci.commands.review.claude import (
    BATCH_SIZE,
    FALLBACK_BETA,
    ReviewSettings,
    review_models,
    system_blocks,
)
from dbt_ci.commands.review.context import collect_models
from dbt_ci.commands.review.index import fail_on_exit_code, report_entry, review
from dbt_ci.commands.review.render import render_review
from dbt_ci.errors import DbtCiError

MODIFIED = "model.shop.orders"
NEW = "model.shop.orders_daily"
SEED = "seed.shop.countries"


def node(name, path, raw, compiled=None, **config):
    """Return a manifest node."""
    return {
        "name": name,
        "original_file_path": path,
        "raw_code": raw,
        "compiled_code": compiled,
        "config": {"materialized": "table", **config},
        "description": "",
        "columns": {},
    }


def manifests():
    """Return the cached change set, both manifests and the recorded run times."""
    target = {
        "metadata": {"adapter_type": "bigquery"},
        "nodes": {
            MODIFIED: node(
                "orders",
                "models/orders.sql",
                "select * from {{ ref('stg') }} where x",
                "select * from `p.d.stg` where x",
                partition_by={"field": "day"},
            ),
            NEW: node("orders_daily", "models/marts/orders_daily.sql", "select 1"),
            SEED: node("countries", "seeds/countries.csv", ""),
            "test.shop.unique_orders_id.abc": {"name": "unique_orders_id"},
        },
        "exposures": {"exposure.shop.revenue": {"name": "revenue"}},
        "child_map": {
            MODIFIED: [
                "test.shop.unique_orders_id.abc",
                "model.shop.orders_daily",
                "exposure.shop.revenue",
            ]
        },
    }
    reference = {"nodes": {MODIFIED: {"raw_code": "select * from {{ ref('stg') }}"}}}
    changes = {
        "modified_nodes": {"model": {MODIFIED: {}}},
        "new_nodes": {"model": {NEW: {}}, "seed": {SEED: {}}},
        "reasons": {MODIFIED: ["models/orders.sql changed"]},
    }
    run_times = {"recorded": {MODIFIED: 120.04, NEW: 1.0}}
    return {
        "cache.json": changes,
        "target_manifest.json": target,
        "reference_manifest.json": reference,
        "run_times.json": run_times,
    }


def fake_cache(files=None):
    """Return a CacheManager stand-in serving the given cached files."""
    files = manifests() if files is None else files
    cache = MagicMock()
    cache.get_cache.side_effect = lambda name="cache.json": files.get(name)
    return cache


class TestCollectModels:
    """What the review is told about each changed model."""

    def test_modified_and_new_models_are_collected(self):
        """Models and snapshots are reviewed; seeds are not."""
        collected = collect_models(fake_cache())
        assert [m["unique_id"] for m in collected.models] == [MODIFIED, NEW]
        assert collected.adapter == "bigquery"

    def test_context_of_a_modified_model(self):
        """The compiled SQL, the diff, config, tests, dependents and run time are included."""
        orders = collect_models(fake_cache()).models[0]
        assert orders["sql"] == "select * from `p.d.stg` where x"
        assert orders["sql_is_compiled"] is True
        assert "+select * from {{ ref('stg') }} where x" in orders["source_diff"]
        assert orders["config"] == {"materialized": "table", "partition_by": {"field": "day"}}
        assert orders["tests"] == ["unique_orders_id"]
        assert orders["downstream_models"] == 1
        assert orders["exposures"] == ["revenue"]
        assert orders["why_changed"] == ["models/orders.sql changed"]
        assert orders["recorded_run_seconds"] == 120.0

    def test_diff_without_trailing_newline(self):
        """Files without a final newline still diff line by line."""
        from dbt_ci.commands.review.context import source_diff

        diff = source_diff("select 1", "select 1\nunion all select 2", "m.sql").splitlines()
        assert diff[-2:] == [" select 1", "+union all select 2"]

    def test_config_without_defaults(self):
        """Unenforced contracts and incremental-only keys on a table are left out."""
        from dbt_ci.commands.review.context import build_config

        table = {
            "materialized": "table",
            "on_schema_change": "ignore",
            "contract": {"enforced": False},
        }
        assert build_config(table) == {"materialized": "table"}
        incremental = {
            "materialized": "incremental",
            "on_schema_change": "fail",
            "unique_key": "id",
        }
        assert build_config(incremental) == incremental

    def test_new_model_has_no_diff_and_raw_sql(self):
        """A new model has no production source, and its raw SQL stands in for compiled."""
        daily = collect_models(fake_cache()).models[1]
        assert "source_diff" not in daily
        assert daily["sql"] == "select 1"
        assert daily["sql_is_compiled"] is False

    def test_exclude_by_path(self):
        """Models whose path matches an exclude pattern are skipped with the reason."""
        collected = collect_models(fake_cache(), exclude=("models/marts/*",))
        assert [m["unique_id"] for m in collected.models] == [MODIFIED]
        assert collected.skipped == {NEW: "excluded by models/marts/*"}

    def test_max_models_keeps_the_slowest(self):
        """The cap drops the models with the shortest recorded run time."""
        collected = collect_models(fake_cache(), max_models=1)
        assert [m["unique_id"] for m in collected.models] == [MODIFIED]
        assert collected.skipped == {NEW: "over review.max-models (1)"}

    def test_model_missing_from_the_manifest(self):
        """A changed node the manifest lacks is skipped rather than failing."""
        files = manifests()
        del files["target_manifest.json"]["nodes"][NEW]
        assert collect_models(fake_cache(files)).skipped == {
            NEW: "not in the pull request's manifest"
        }

    def test_no_change_set(self):
        """Without a change set there is nothing to review."""
        assert collect_models(fake_cache({})).models == []


def response(answer=None, stop_reason="end_turn", model="claude-opus-5-5", text=True):
    """Return an object shaped like a Messages API response."""
    content = [SimpleNamespace(type="text", text=json.dumps(answer or {}))] if text else []
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category="cyber") if stop_reason == "refusal" else None,
        model=model,
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=20,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=50,
        ),
    )


FINDING = {
    "model": MODIFIED,
    "severity": "high",
    "category": "performance",
    "title": "Full scan",
    "detail": "Scans every partition.",
    "suggestion": "Filter on day.",
}


def models(count):
    """Return model contexts to review."""
    return [{"unique_id": f"model.p.m{i}", "name": f"m{i}"} for i in range(count)]


class TestReviewModels:
    """How the models are sent to Claude and the answers combined."""

    def test_batches_and_usage(self):
        """Models go in batches; findings, summaries and tokens add up across them."""
        client = MagicMock()
        client.beta.messages.create.return_value = response(
            {"summary": "Looks fine.", "findings": [FINDING]}
        )
        result = review_models(client, models(BATCH_SIZE + 2), ReviewSettings())
        assert client.beta.messages.create.call_count == 2
        assert len(result.findings) == 2
        assert result.summaries == ["Looks fine.", "Looks fine."]
        assert result.usage["input_tokens"] == 200
        assert result.usage["cache_read_input_tokens"] == 100
        assert result.served_by == {"claude-opus-5-5"}

    def test_request_shape(self):
        """Structured output, effort, a cached system prompt and fallbacks on Opus 5.5."""
        client = MagicMock()
        client.beta.messages.create.return_value = response({"summary": "", "findings": []})
        review_models(client, models(1), ReviewSettings(effort="high"), adapter="snowflake")
        params = client.beta.messages.create.call_args.kwargs
        assert params["model"] == "claude-opus-5-5"
        assert params["output_config"]["effort"] == "high"
        assert params["output_config"]["format"]["type"] == "json_schema"
        assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert params["betas"] == [FALLBACK_BETA]
        assert params["fallbacks"] == "default"
        payload = json.loads(params["messages"][0]["content"].split("\n\n", 1)[1])
        assert payload["warehouse"] == "snowflake"

    def test_no_fallbacks_on_other_models(self):
        """Models that do not take server-side fallbacks are called without them."""
        client = MagicMock()
        client.beta.messages.create.return_value = response({"summary": "", "findings": []})
        review_models(client, models(1), ReviewSettings(model="claude-haiku-5-5"))
        params = client.beta.messages.create.call_args.kwargs
        assert "fallbacks" not in params and "betas" not in params

    @pytest.mark.parametrize(
        "failure",
        [
            response(stop_reason="refusal"),
            response(stop_reason="max_tokens"),
            response(text=False),
            RuntimeError("overloaded"),
        ],
    )
    def test_a_failed_batch_keeps_the_others(self, failure):
        """A refusal, a cut-off answer or an API error loses only its own batch."""
        client = MagicMock()
        good = response({"summary": "ok", "findings": [FINDING]})
        client.beta.messages.create.side_effect = [failure, good]
        result = review_models(client, models(BATCH_SIZE + 1), ReviewSettings())
        assert len(result.errors) == 1
        assert result.findings == [FINDING]

    def test_team_instructions_join_the_system_prompt(self):
        """Instructions are appended to the system prompt; without them it is unchanged."""
        assert "We deploy on BigQuery" in system_blocks("We deploy on BigQuery")[0]["text"]
        assert system_blocks(None) == system_blocks("  ")


class TestRealSdk:
    """The request the Anthropic SDK actually sends, with a stubbed HTTP transport."""

    def test_request_and_parsing(self):
        """The SDK accepts the parameters, and its response objects parse."""
        anthropic = pytest.importorskip("anthropic")
        httpx2 = pytest.importorskip("httpx2")
        sent = {}

        def handler(request):
            sent["beta"] = request.headers.get("anthropic-beta")
            sent["body"] = json.loads(request.content)
            answer = {"summary": "One issue.", "findings": [FINDING]}
            return httpx2.Response(
                200,
                json={
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-opus-5-5",
                    "content": [{"type": "text", "text": json.dumps(answer)}],
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            )

        client = anthropic.Anthropic(
            api_key="test", http_client=httpx2.Client(transport=httpx2.MockTransport(handler))
        )
        result = review_models(client, models(1), ReviewSettings())
        assert result.findings == [FINDING]
        assert sent["beta"] == FALLBACK_BETA
        assert sent["body"]["fallbacks"] == "default"
        assert sent["body"]["output_config"]["format"]["schema"]["required"] == [
            "summary",
            "findings",
        ]


RECORD = {
    "model": "claude-opus-5-5",
    "models": {MODIFIED: "orders", NEW: "orders_daily"},
    "skipped": {},
    "findings": [
        {**FINDING, "severity": "low", "title": "Minor"},
        {**FINDING, "suggestion": "Filter on day:\n```sql\nwhere day > current_date - 3\n```"},
    ],
    "summaries": ["Two models changed."],
    "errors": [],
}


class TestRender:
    """The markdown the review and the report show."""

    def test_findings_sorted_by_severity(self):
        """High findings come first, with the model's name and an indented suggestion."""
        text = "\n".join(render_review(RECORD))
        assert text.index("**high**") < text.index("**low**")
        assert "`orders`" in text
        assert "  ```sql\n  where day > current_date - 3\n  ```" in text
        assert "Reviewed 2 model(s) with `claude-opus-5-5`" in text

    def test_no_findings(self):
        """A clean review says so."""
        assert "No findings." in render_review({**RECORD, "findings": []})

    def test_review_that_did_not_run(self):
        """A skipped review says why, and nothing else."""
        lines = render_review({**RECORD, "skipped_reason": "dry run"})
        assert lines == ["### AI review", "", "Not run: dry run.", ""]

    def test_no_review(self):
        """Without review.json the report has no section."""
        assert render_review(None) == []


class TestFailOn:
    """--fail-on turns findings into a failing exit code."""

    @pytest.mark.parametrize(
        "fail_on, code", [(None, 0), ("never", 0), ("high", 1), ("medium", 1), ("low", 1)]
    )
    def test_threshold(self, fail_on, code):
        """A high finding fails every threshold but never."""
        assert fail_on_exit_code(RECORD, fail_on) == code

    def test_below_threshold_passes(self):
        """Only low findings do not fail --fail-on medium."""
        low_only = {**RECORD, "findings": [{**FINDING, "severity": "low"}]}
        assert fail_on_exit_code(low_only, "medium") == 0

    def test_report_entry_counts(self):
        """report.json counts the findings per severity."""
        assert report_entry(RECORD)["findings"] == {"high": 1, "medium": 0, "low": 1}


class TestReviewCommand:
    """The review command end to end, with the cache and Claude stubbed."""

    @staticmethod
    def run(args=None, client=None, files=None, make_client_error=None):
        """Run review and return the exit code, the cache and what was echoed."""
        cache = fake_cache(files)
        args = Namespace(
            **{"format": "markdown", "output": None, "fail_on": "never", **(args or {})}
        )
        make_client = MagicMock(return_value=client, side_effect=make_client_error)
        with (
            patch("dbt_ci.commands.review.index.CacheManager", return_value=cache),
            patch("dbt_ci.commands.review.index.make_client", make_client),
            patch("dbt_ci.commands.review.index.click") as click,
            pytest.raises(SystemExit) as exc,
        ):
            review(args)
        echoed = "".join(str(c.args[0]) for c in click.echo.call_args_list)
        return exc.value.code, cache, echoed, make_client

    def test_writes_review_and_report_entry(self):
        """Findings land in review.json, report.json and the output."""
        client = MagicMock()
        client.beta.messages.create.return_value = response(
            {"summary": "One issue.", "findings": [FINDING]}
        )
        code, cache, echoed, _ = self.run(client=client)
        assert code == 0
        record = cache.write_review.call_args.args[0]
        assert record["findings"] == [FINDING]
        assert record["models"] == {MODIFIED: "orders", NEW: "orders_daily"}
        cache.update_report.assert_called_with(
            "review",
            "completed",
            {
                "model": "claude-opus-5-5",
                "reviewed": 2,
                "findings": {"high": 1, "medium": 0, "low": 0},
            },
        )
        assert "## dbt-ci AI review" in echoed and "Full scan" in echoed

    def test_fail_on_high(self):
        """A high finding with --fail-on high exits 1, after recording the review."""
        client = MagicMock()
        client.beta.messages.create.return_value = response({"summary": "", "findings": [FINDING]})
        code, cache, _, _ = self.run({"fail_on": "high"}, client=client)
        assert code == 1
        cache.write_review.assert_called_once()

    def test_dry_run_sends_nothing(self):
        """A dry run lists the models and never creates a client."""
        code, cache, _, make_client = self.run({"dry_run": True})
        assert code == 0
        make_client.assert_not_called()
        assert cache.write_review.call_args.args[0]["skipped_reason"] == "dry run"

    def test_missing_sdk_is_skipped_not_failed(self):
        """Without the SDK the review is skipped with the install hint, and exits 0."""
        code, cache, _, _ = self.run(make_client_error=DbtCiError("pip install 'dbt-ci[ai]'"))
        assert code == 0
        assert cache.update_report.call_args.args[1] == "skipped"

    def test_json_output(self, tmp_path):
        """--format json writes review.json's content to --output."""
        out = tmp_path / "review.json"
        code, _, _, _ = self.run({"format": "json", "output": str(out), "dry_run": True})
        assert code == 0
        assert json.loads(out.read_text())["skipped_reason"] == "dry run"

    def test_no_init(self):
        """Without init's cache the command fails."""
        code, _, _, _ = self.run(files={})
        assert code == 1


class TestReportSection:
    """report shows the review after the change set."""

    def test_report_includes_review(self):
        """The markdown report and the JSON output both carry the review."""
        from dbt_ci.commands.report.index import render_markdown

        cache = MagicMock()
        cache.get_cache.side_effect = lambda name="cache.json": (
            RECORD if name == "review.json" else None
        )
        with patch("dbt_ci.commands.report.index.CacheManager", return_value=cache):
            text = render_markdown(None, None, Namespace())
        assert "### AI review" in text and "Full scan" in text


class TestConfig:
    """The review: section of dbt-ci.config.yaml."""

    def test_section_validates(self):
        """Every review key is accepted, and bad values are reported."""
        from dbt_ci.cli.config.schema import validate_config

        good = {
            "review": {
                "model": "claude-sonnet-5-5",
                "effort": "high",
                "max-models": 10,
                "exclude": ["models/legacy/*"],
                "instructions": "We use BigQuery.",
                "fail-on": "high",
                "format": "json",
                "output": "review.md",
                "dry-run": True,
            }
        }
        assert validate_config(good) == []
        assert validate_config({"review": {"fail-on": "sometimes"}})
        assert validate_config({"review": {"max-models": "ten"}})

    def test_config_file_reaches_the_command(self, tmp_path):
        """Settings under review:, and per event under on:, become the command's options."""
        from click.testing import CliRunner
        from dbt_ci.main import cli

        config = tmp_path / "dbt-ci.config.yaml"
        config.write_text(
            "review:\n"
            "  model: claude-sonnet-5-5\n"
            "  max-models: 5\n"
            "  exclude: [models/legacy/*, models/tmp/*]\n"
            "on:\n"
            "  pull-request:\n"
            "    review:\n"
            "      fail-on: high\n"
        )
        seen = {}
        with patch("dbt_ci.commands.review.cli.review", side_effect=lambda a: seen.update(vars(a))):
            result = CliRunner().invoke(
                cli, ["review", "--config", str(config), "--event", "pull-request"]
            )
        assert result.exit_code == 0, result.output
        assert seen["model"] == "claude-sonnet-5-5"
        assert seen["max_models"] == 5
        assert seen["exclude"] == ("models/legacy/*", "models/tmp/*")
        assert seen["fail_on"] == "high"
        assert seen["effort"] == "medium"
