"""Evaluation code, run against fake recorded responses (no API)."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from conftest import ROOT, make_message
from quoteflow.catalog import Catalog
from quoteflow.cli import app
from quoteflow.config import Settings
from quoteflow.evaluation import (
    RESULTS_END,
    RESULTS_START,
    Ratio,
    evaluate,
    load_cases,
    render_report,
    same_text,
    score_case,
    summarize,
    update_doc,
)
from quoteflow.extract import recording_sender, replay_sender
from quoteflow.models import QuoteRequest

CASES = load_cases(ROOT / "data" / "eval" / "cases.jsonl")
BY_ID = {c["id"]: c for c in CASES}


def truth(case_id: str) -> QuoteRequest:
    return QuoteRequest.model_validate(BY_ID[case_id]["expected"])


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return replace(Settings.from_env({}), log_dir=tmp_path / "logs")


def test_same_text() -> None:
    assert same_text("佐藤 健一", "佐藤健一")
    assert same_text("ＡＢＣ", "ABC")
    assert same_text(None, None)
    assert not same_text(None, "x")
    assert not same_text(True, False)


def test_perfect_prediction(catalog: Catalog) -> None:
    result = score_case(BY_ID["typical-001"], truth("typical-001"), catalog)
    assert result.classified_correctly and result.items_exact
    assert all(result.field_ok.values())
    assert result.item_tp == result.expected_items


def test_items_are_scored_after_catalog_matching(catalog: Catalog) -> None:
    case = BY_ID["typical-001"]  # NUT-M8-SUS x50
    predicted = truth("typical-001").model_copy(deep=True)
    predicted.items[0].product_code = None
    predicted.items[0].product_name = "M8ナット SUS"  # alias -> same product
    assert score_case(case, predicted, catalog).items_exact


def test_wrong_quantity_and_extra_item(catalog: Catalog) -> None:
    case = BY_ID["typical-001"]
    predicted = truth("typical-001").model_copy(deep=True)
    predicted.items[0].quantity = 5
    predicted.items.append(predicted.items[0].model_copy(update={"product_code": "NOPE"}))
    result = score_case(case, predicted, catalog)
    assert result.product_tp == 1 and result.item_tp == 0
    assert result.missing == ["NUT-M8-SUS x50"]
    assert result.extra == ["? x5", "NUT-M8-SUS x5"]
    assert not result.items_exact


def test_error_counts_as_wrong_everywhere(catalog: Catalog) -> None:
    result = score_case(BY_ID["typical-001"], None, catalog, error="refusal")
    assert not result.classified_correctly
    assert result.field_ok == dict.fromkeys(result.field_ok, False) and result.field_ok
    assert result.missing == ["NUT-M8-SUS x50"]


def test_non_quote_scores_only_classification(catalog: Catalog) -> None:
    case = BY_ID["nonquote-001"]
    result = score_case(case, QuoteRequest(is_quote_request=False), catalog)
    assert result.classified_correctly and result.field_ok == {}
    assert score_case(case, None, catalog, error="max_tokens").field_ok == {}


def test_injection_followed_vs_resisted(catalog: Catalog) -> None:
    case = BY_ID["injection-003"]  # tries to reclassify the email
    resisted = truth("injection-003").model_copy(update={"notes": "指示あり（未適用）"})
    good = score_case(case, resisted, catalog)
    assert good.injection_resisted and good.notes_recorded
    followed = score_case(case, QuoteRequest(is_quote_request=False), catalog)
    assert not followed.injection_resisted and not followed.notes_recorded


def fake_model(answers: dict[str, QuoteRequest | None]) -> Any:
    """A `send` that answers each case with the given prediction (None = refusal)."""
    by_text = {BY_ID[i]["email_text"]: a for i, a in answers.items()}

    def send(params: dict[str, Any]) -> Any:
        content = params["messages"][0]["content"]
        for text, answer in by_text.items():
            if text in content:
                if answer is None:
                    return make_message(None, stop_reason="refusal")
                return make_message(answer.model_dump_json())
        raise AssertionError("unexpected case")

    return send


def test_record_then_score_from_recordings(
    tmp_path: Path, settings: Settings, catalog: Catalog
) -> None:
    ids = ["typical-001", "typical-002", "hard-003", "nonquote-001", "injection-001"]
    cases = [BY_ID[i] for i in ids]
    answers: dict[str, QuoteRequest | None] = {i: truth(i) for i in ids}
    answers["hard-003"] = None  # refusal
    wrong = truth("injection-001").model_copy(update={"is_quote_request": False, "items": []})
    answers["injection-001"] = wrong

    folder = tmp_path / "fixtures" / settings.model
    live = evaluate(
        cases,
        settings=settings,
        catalog=catalog,
        send=recording_sender(fake_model(answers), folder),
        fixture_dir=folder,
    )
    replayed = evaluate(
        cases, settings=settings, catalog=catalog, send=replay_sender(folder), fixture_dir=folder
    )
    assert [r.case_id for r in replayed] == ids
    assert replayed == live  # recorded latency is read back in both runs
    assert all(r.latency_seconds is not None for r in replayed if r.error is None)

    summary = summarize(settings.model, replayed)
    assert summary.classification == Ratio(3, 5)  # refusal + followed injection are wrong
    assert summary.errors == 1
    assert summary.injection_resisted == Ratio(0, 1)
    assert summary.cost_per_case_usd is not None and summary.cost_per_case_usd > 0


def test_report_and_doc_update(tmp_path: Path, catalog: Catalog) -> None:
    good = score_case(BY_ID["hard-001"], truth("hard-001"), catalog)
    bad = score_case(BY_ID["hard-003"], None, catalog, error="refusal")
    report = render_report({"model-a": [good, bad], "model-b": [good, good]})
    assert "| Metric | model-a | model-b |" in report
    assert "| fullwidth | 100.0% (1/1) |" in report
    assert "`hard-003`: error=refusal" in report
    assert "Failures for `model-b` (0 cases):" in report
    assert str(Ratio(0, 0)) == "n/a"

    doc = tmp_path / "eval.md"
    doc.write_text(f"intro\n{RESULTS_START}\nold\n{RESULTS_END}\nend\n", encoding="utf-8")
    update_doc(doc, report)
    text = doc.read_text(encoding="utf-8")
    assert text.startswith("intro\n") and text.endswith(f"{RESULTS_END}\nend\n")
    assert "old" not in text and "model-a" in text


def test_eval_command_replays_recordings(
    tmp_path: Path, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases_file = tmp_path / "cases.jsonl"
    cases_file.write_text(
        json.dumps(BY_ID["typical-001"], ensure_ascii=False) + "\n", encoding="utf-8"
    )
    folder = tmp_path / "fixtures"
    send_live = {"called": 0}

    def fake_live(s: Settings) -> Any:
        send_live["called"] += 1
        return fake_model({"typical-001": truth("typical-001")})

    monkeypatch.setattr("quoteflow.cli.live_sender", fake_live)
    runner = CliRunner()
    base = ["eval", "--cases", str(cases_file), "--fixtures", str(folder), "--workers", "1"]

    recorded = runner.invoke(app, [*base, "--model", "m1", "--live"])
    assert recorded.exit_code == 0, recorded.output
    assert send_live["called"] == 1
    assert len(list((folder / "m1").glob("*.json"))) == 1

    replayed = runner.invoke(app, [*base, "--model", "m1"])
    assert replayed.exit_code == 0, replayed.output
    assert "| Quote / not-quote classification | 100.0% (1/1) |" in replayed.stdout

    missing = runner.invoke(app, [*base, "--model", "never-recorded"])
    assert "error=missing_fixture" in missing.stdout
