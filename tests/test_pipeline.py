"""End-to-end runs over the demo samples, with saved responses instead of the API."""

import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from conftest import ROOT, make_message
from quoteflow.catalog import Catalog
from quoteflow.config import PricingRules, Settings
from quoteflow.extract import replay_sender
from quoteflow.models import QuoteRequest
from quoteflow.pipeline import run_pipeline
from quoteflow.review import ReviewResult

SAMPLES = ROOT / "data" / "samples"
FIXTURES = ROOT / "evals" / "fixtures" / "demo"
DAY = date(2026, 11, 9)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return replace(Settings.from_env({}), log_dir=tmp_path / "logs")


def run(
    name: str,
    settings: Settings,
    catalog: Catalog,
    rules: PricingRules,
    tmp_path: Path,
    reviewer: Any = None,
    send: Any = None,
) -> Any:
    return run_pipeline(
        SAMPLES / name,
        settings=settings,
        catalog=catalog,
        rules=rules,
        send=send or replay_sender(FIXTURES),
        reviewer=reviewer,
        out_dir=tmp_path / "out",
        issue_date=DAY,
        received_at=DAY,
    )


def log_lines(settings: Settings) -> list[dict[str, Any]]:
    text = (settings.log_dir / "runs.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def approve(request: QuoteRequest) -> ReviewResult:
    return ReviewResult(approved=True, request=request, issues=[])


def test_email_auto_approved_when_clean(
    settings: Settings, catalog: Catalog, rules: PricingRules, tmp_path: Path
) -> None:
    result = run("request_01.txt", settings, catalog, rules, tmp_path)
    assert result.status == "completed"
    assert result.quote.total == 19437
    assert result.pdf_path.exists()
    [line] = log_lines(settings)
    assert line["status"] == "completed"
    assert line["mode"] == "ai"
    assert line["warning_count"] == 0
    assert line["total_yen"] == 19437


def test_log_never_contains_names_or_addresses(
    settings: Settings, catalog: Catalog, rules: PricingRules, tmp_path: Path
) -> None:
    run("request_03.eml", settings, catalog, rules, tmp_path)
    raw = (settings.log_dir / "runs.jsonl").read_text(encoding="utf-8")
    for secret in ("ソラノ", "鈴木", "m.suzuki", "sorano-ss.example"):
        assert secret not in raw
    assert log_lines(settings)[0]["company"].startswith("#")


def test_injection_stops_auto_approval(
    settings: Settings, catalog: Catalog, rules: PricingRules, tmp_path: Path
) -> None:
    result = run("request_04_injection.txt", settings, catalog, rules, tmp_path)
    assert result.status == "needs_review"
    assert "90%引き" in result.request.notes
    assert result.quote is None
    assert not (tmp_path / "out").exists()


def test_injection_quote_after_review_uses_list_prices(
    settings: Settings, catalog: Catalog, rules: PricingRules, tmp_path: Path
) -> None:
    result = run("request_04_injection.txt", settings, catalog, rules, tmp_path, reviewer=approve)
    assert result.status == "completed"
    assert result.quote.total == 25132  # same as the ground truth: the instruction was not applied


def test_not_quote_is_stopped(
    settings: Settings, catalog: Catalog, rules: PricingRules, tmp_path: Path
) -> None:
    result = run("request_05_not_quote.txt", settings, catalog, rules, tmp_path)
    assert result.status == "needs_review"
    assert [i.code for i in result.issues] == ["not_quote_request"]


def test_reviewer_abort(
    settings: Settings, catalog: Catalog, rules: PricingRules, tmp_path: Path
) -> None:
    def abort(request: QuoteRequest) -> ReviewResult:
        return ReviewResult(approved=False, request=request, issues=[])

    result = run("request_01.txt", settings, catalog, rules, tmp_path, reviewer=abort)
    assert result.status == "aborted"
    assert log_lines(settings)[0]["status"] == "aborted"


def test_excel_form_needs_no_ai(
    settings: Settings, catalog: Catalog, rules: PricingRules, tmp_path: Path
) -> None:
    def no_api(params: dict[str, Any]) -> Any:
        raise AssertionError("the Excel form must not call the API")

    result = run(
        "request_02.xlsx", settings, catalog, rules, tmp_path, reviewer=approve, send=no_api
    )
    assert result.status == "completed"
    assert result.quote.total == 25844
    assert log_lines(settings)[0]["mode"] == "form"
    assert log_lines(settings)[0]["input_tokens"] == 0


def test_extraction_failure_is_logged_with_reason(
    settings: Settings, catalog: Catalog, rules: PricingRules, tmp_path: Path
) -> None:
    def refuse(params: dict[str, Any]) -> Any:
        return make_message(None, stop_reason="refusal")

    result = run("request_01.txt", settings, catalog, rules, tmp_path, send=refuse)
    assert result.status == "failed"
    assert "refusal" in result.message
    assert log_lines(settings)[0]["error_reason"] == "refusal"


def test_cost_is_estimated_from_usage(
    settings: Settings, catalog: Catalog, rules: PricingRules, tmp_path: Path
) -> None:
    text = (SAMPLES / "request_01.expected.json").read_text(encoding="utf-8")

    def live_like(params: dict[str, Any]) -> Any:
        return make_message(text)  # 1,200 input + 150 output tokens on claude-opus-5-5

    run("request_01.txt", settings, catalog, rules, tmp_path, send=live_like)
    line = log_lines(settings)[0]
    assert (line["input_tokens"], line["output_tokens"]) == (1200, 150)
    assert line["estimated_cost_usd"] == "0.007800"  # 1200*4/1M + 150*20/1M


def test_pricing_failure_after_approval(
    settings: Settings, catalog: Catalog, rules: PricingRules, tmp_path: Path
) -> None:
    def approve_broken(request: QuoteRequest) -> ReviewResult:
        broken = request.model_copy(update={"items": []})
        return ReviewResult(approved=True, request=broken, issues=[])

    result = run("request_01.txt", settings, catalog, rules, tmp_path, reviewer=approve_broken)
    assert result.status == "failed"
    assert log_lines(settings)[0]["error_reason"] == "pricing"


def test_unsupported_file_and_missing_sender(
    settings: Settings, catalog: Catalog, rules: PricingRules, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="unsupported file type"):
        run_pipeline(
            ROOT / "README.md",
            settings=settings,
            catalog=catalog,
            rules=rules,
            send=None,
            reviewer=None,
            out_dir=tmp_path,
            issue_date=DAY,
        )
    with pytest.raises(ValueError, match="needs a Send"):
        run_pipeline(
            SAMPLES / "request_01.txt",
            settings=settings,
            catalog=catalog,
            rules=rules,
            send=None,
            reviewer=None,
            out_dir=tmp_path,
            issue_date=DAY,
        )
