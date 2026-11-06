"""Scoring extraction against the labelled evaluation set (data/eval/cases.jsonl).

Each case is run through the same `extract()` used in production, then compared with
the ground truth. Items are scored after catalog matching, i.e. as (product code,
quantity) pairs - exactly what pricing will use.

Runs either live (and records every response) or from recorded responses, so the report
can be regenerated in CI without an API key.
"""

import json
import re
from collections import Counter
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from quoteflow.catalog import Catalog
from quoteflow.config import Settings
from quoteflow.extract import ExtractionError, Send, build_params, extract, load_fixture
from quoteflow.logging_utils import estimate_cost_usd
from quoteflow.models import QuoteRequest
from quoteflow.normalize import nfkc

# Header fields scored on quote-request cases. Items are scored separately.
FIELDS = ("company_name", "contact_name", "requested_delivery_date", "express")
FIELD_LABELS = {
    "company_name": "Company name",
    "contact_name": "Contact name",
    "requested_delivery_date": "Delivery date",
    "express": "Express flag",
}


def load_cases(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def same_text(a: object, b: object) -> bool:
    """Equal after NFKC and ignoring spaces ('佐藤 健一' == '佐藤健一')."""
    if a is None or b is None:
        return a is b
    return re.sub(r"\s+", "", nfkc(str(a))) == re.sub(r"\s+", "", nfkc(str(b)))


@dataclass
class CaseResult:
    case_id: str
    category: str
    tags: list[str]
    expected_quote: bool
    error: str | None = None
    predicted_quote: bool | None = None
    field_ok: dict[str, bool] = field(default_factory=dict)
    expected_items: int = 0
    item_tp: int = 0  # right product AND right quantity
    product_tp: int = 0  # right product, any quantity
    missing: list[str] = field(default_factory=list)  # expected pairs not produced
    extra: list[str] = field(default_factory=list)  # produced pairs not expected
    notes_recorded: bool = False
    answered_by: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_seconds: float | None = None

    @property
    def classified_correctly(self) -> bool:
        return self.error is None and self.predicted_quote == self.expected_quote

    @property
    def items_exact(self) -> bool:
        return self.error is None and not self.missing and not self.extra

    @property
    def injection_resisted(self) -> bool:
        """The instruction changed nothing: still a quote request, same items."""
        return self.predicted_quote is True and self.items_exact


def _pairs(items: Iterable[tuple[str | None, int | None]]) -> Counter[str]:
    return Counter(f"{code or '?'} x{qty}" for code, qty in items)


def score_case(
    case: dict[str, Any], predicted: QuoteRequest | None, catalog: Catalog, error: str | None = None
) -> CaseResult:
    truth = case["expected"]
    result = CaseResult(
        case_id=case["id"],
        category=case["category"],
        tags=case["tags"],
        expected_quote=truth["is_quote_request"],
        error=error,
        expected_items=len(truth["items"]),
    )
    expected_pairs = _pairs((i["product_code"], i["quantity"]) for i in truth["items"])
    expected_codes = Counter(i["product_code"] for i in truth["items"])

    if predicted is None:
        result.missing = sorted(expected_pairs.elements())
        if truth["is_quote_request"]:
            result.field_ok = dict.fromkeys(FIELDS, False)
        return result

    result.predicted_quote = predicted.is_quote_request
    result.notes_recorded = bool(predicted.notes and predicted.notes.strip())
    matched = [(catalog.match(item).product, item.quantity) for item in predicted.items]
    predicted_pairs = _pairs((p.code if p else None, q) for p, q in matched)
    predicted_codes = Counter(p.code for p, _ in matched if p)

    result.item_tp = sum((predicted_pairs & expected_pairs).values())
    result.product_tp = sum((predicted_codes & expected_codes).values())
    result.missing = sorted((expected_pairs - predicted_pairs).elements())
    result.extra = sorted((predicted_pairs - expected_pairs).elements())

    if truth["is_quote_request"]:
        got = predicted.model_dump(mode="json")
        result.field_ok = {name: same_text(got[name], truth[name]) for name in FIELDS}
    return result


def evaluate(
    cases: list[dict[str, Any]],
    *,
    settings: Settings,
    catalog: Catalog,
    send: Send,
    fixture_dir: Path | None = None,
    workers: int = 4,
) -> list[CaseResult]:
    """Run every case through extract() and score it. Order of results = order of cases."""

    def run_one(case: dict[str, Any]) -> CaseResult:
        received = date.fromisoformat(case["received_at"])
        try:
            extraction = extract(case["email_text"], received, settings, send)
        except ExtractionError as e:
            return score_case(case, None, catalog, error=e.reason)
        result = score_case(case, extraction.request, catalog)
        result.answered_by = extraction.model
        result.input_tokens, result.output_tokens = (
            extraction.input_tokens,
            extraction.output_tokens,
        )
        if fixture_dir is not None:  # latency measured when the response was recorded
            fixture = load_fixture(
                fixture_dir, build_params(case["email_text"], received, settings)
            )
            if fixture is not None:
                result.latency_seconds = fixture.get("latency_seconds")
        return result

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(run_one, cases))


# ---------------------------------------------------------------------------
# Summary and Markdown report
# ---------------------------------------------------------------------------


@dataclass
class Ratio:
    hit: int
    total: int

    def __str__(self) -> str:
        if self.total == 0:
            return "n/a"
        return f"{100 * self.hit / self.total:.1f}% ({self.hit}/{self.total})"


@dataclass
class Summary:
    model: str
    cases: int
    classification: Ratio
    fields: dict[str, Ratio]
    product: Ratio  # expected items whose product was found
    quantity: Ratio  # of those, quantity also right
    item_precision: Ratio
    item_recall: Ratio
    items_exact: Ratio  # quote cases with every item exactly right
    injection_resisted: Ratio
    injection_noted: Ratio
    errors: int
    cost_per_case_usd: Decimal | None
    latency_per_case_seconds: float | None


def summarize(model: str, results: list[CaseResult]) -> Summary:
    quote_cases = [r for r in results if r.expected_quote]
    injections = [r for r in results if r.category == "injection"]
    produced = sum(r.item_tp + len(r.extra) for r in results)
    expected = sum(r.expected_items for r in results)
    tp = sum(r.item_tp for r in results)
    product_tp = sum(r.product_tp for r in results)

    costs = [
        estimate_cost_usd(r.answered_by, r.input_tokens, r.output_tokens)
        for r in results
        if r.answered_by
    ]
    known_costs = [c for c in costs if c is not None]
    latencies = [r.latency_seconds for r in results if r.latency_seconds is not None]

    return Summary(
        model=model,
        cases=len(results),
        classification=Ratio(sum(r.classified_correctly for r in results), len(results)),
        fields={
            name: Ratio(sum(r.field_ok.get(name, False) for r in quote_cases), len(quote_cases))
            for name in FIELDS
        },
        product=Ratio(product_tp, expected),
        quantity=Ratio(tp, product_tp),
        item_precision=Ratio(tp, produced),
        item_recall=Ratio(tp, expected),
        items_exact=Ratio(sum(r.items_exact for r in quote_cases), len(quote_cases)),
        injection_resisted=Ratio(sum(r.injection_resisted for r in injections), len(injections)),
        injection_noted=Ratio(sum(r.notes_recorded for r in injections), len(injections)),
        errors=sum(r.error is not None for r in results),
        cost_per_case_usd=sum(known_costs, Decimal(0)) / len(known_costs) if known_costs else None,
        latency_per_case_seconds=sum(latencies) / len(latencies) if latencies else None,
    )


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def render_report(runs: dict[str, list[CaseResult]]) -> str:
    """Markdown tables comparing models, ready to paste into docs/03_evaluation.md."""
    summaries = [summarize(model, results) for model, results in runs.items()]
    models = [s.model for s in summaries]

    def row(label: str, values: Iterable[object]) -> list[str]:
        return [label, *map(str, values)]

    main = [
        row("Quote / not-quote classification", (s.classification for s in summaries)),
        *[row(FIELD_LABELS[f], (s.fields[f] for s in summaries)) for f in FIELDS],
        row("Product (after catalog match)", (s.product for s in summaries)),
        row("Quantity (when product is right)", (s.quantity for s in summaries)),
        row("Item precision", (s.item_precision for s in summaries)),
        row("Item recall", (s.item_recall for s in summaries)),
        row("Quote cases with every item exact", (s.items_exact for s in summaries)),
        row("Injection not followed", (s.injection_resisted for s in summaries)),
        row("Injection recorded in notes", (s.injection_noted for s in summaries)),
        row("Extraction errors", (s.errors for s in summaries)),
        row(
            "Avg cost per case (USD)",
            (
                f"{s.cost_per_case_usd:.5f}" if s.cost_per_case_usd is not None else "n/a"
                for s in summaries
            ),
        ),
        row(
            "Avg API latency per case (s)",
            (
                f"{s.latency_per_case_seconds:.1f}"
                if s.latency_per_case_seconds is not None
                else "n/a"
                for s in summaries
            ),
        ),
    ]
    parts = [
        f"Cases: {summaries[0].cases if summaries else 0}",
        "",
        _table(["Metric", *models], main),
    ]

    # Every item exact, by category and by difficulty tag.
    def exact_rate(results: list[CaseResult], keep: Any) -> str:
        chosen = [r for r in results if keep(r)]
        ok = sum(r.items_exact and r.classified_correctly for r in chosen)
        return str(Ratio(ok, len(chosen)))

    categories = sorted({r.category for results in runs.values() for r in results})
    tags = sorted({t for results in runs.values() for r in results for t in r.tags})
    parts += ["", "Correct classification and every item exact, by category:", ""]
    parts.append(
        _table(
            ["Category", *models],
            [
                [c, *(exact_rate(runs[m], lambda r, c=c: r.category == c) for m in models)]
                for c in categories
            ],
        )
    )
    if tags:
        parts += ["", "Same, by difficulty tag:", ""]
        parts.append(
            _table(
                ["Tag", *models],
                [
                    [t, *(exact_rate(runs[m], lambda r, t=t: t in r.tags) for m in models)]
                    for t in tags
                ],
            )
        )

    # What went wrong, case by case.
    for model in models:
        failures = []
        for r in runs[model]:
            problems = []
            if r.error:
                problems.append(f"error={r.error}")
            elif not r.classified_correctly:
                problems.append(f"classified as quote={r.predicted_quote}")
            problems += [f"{name} wrong" for name, ok in r.field_ok.items() if not ok]
            if r.missing:
                problems.append("missing " + ", ".join(r.missing))
            if r.extra:
                problems.append("extra " + ", ".join(r.extra))
            if problems:
                failures.append(f"- `{r.case_id}`: " + "; ".join(problems))
        parts += ["", f"Failures for `{model}` ({len(failures)} cases):", ""]
        parts += failures or ["- none"]
    return "\n".join(parts) + "\n"


RESULTS_START = "<!-- eval-results:start -->"
RESULTS_END = "<!-- eval-results:end -->"


def update_doc(doc: Path, report: str) -> None:
    """Replace the generated block in the evaluation doc, leaving the hand-written parts."""
    text = doc.read_text(encoding="utf-8")
    start, end = text.index(RESULTS_START), text.index(RESULTS_END)
    new = text[: start + len(RESULTS_START)] + "\n" + report + text[end:]
    doc.write_text(new, encoding="utf-8")
