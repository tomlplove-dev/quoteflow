"""The whole flow for one request file:

    read -> extract (Claude, or code for the Excel form) -> validate -> human review
         -> price (code) -> PDF (code) -> one log line

Each stage can stop the flow; the result says where and why.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from quoteflow.catalog import Catalog
from quoteflow.config import PricingRules, Settings
from quoteflow.extract import ExtractionError, Send, extract
from quoteflow.inputs import EMAIL_SUFFIXES, FORM_SUFFIXES, read_email, read_form
from quoteflow.logging_utils import RunRecord, estimate_cost_usd, mask, write_run_record
from quoteflow.models import Quote, QuoteRequest
from quoteflow.pricing import PricingError, calculate_quote
from quoteflow.render_pdf import render_quote_pdf
from quoteflow.review import ReviewResult
from quoteflow.validate import Issue, validate_request

Reviewer = Callable[[QuoteRequest], ReviewResult]


@dataclass
class PipelineResult:
    status: str  # completed | aborted | needs_review | failed
    message: str
    record: RunRecord
    request: QuoteRequest | None = None
    issues: list[Issue] | None = None
    quote: Quote | None = None
    pdf_path: Path | None = None


def run_pipeline(
    path: Path,
    *,
    settings: Settings,
    catalog: Catalog,
    rules: PricingRules,
    send: Send | None,
    reviewer: Reviewer | None,
    out_dir: Path,
    issue_date: date,
    received_at: date | None = None,
) -> PipelineResult:
    """Process one file. `reviewer=None` means auto-approve, allowed only with zero issues."""
    started = time.perf_counter()
    suffix = path.suffix.lower()
    record = RunRecord(
        source_file=path.name, status="failed", mode="form" if suffix in FORM_SUFFIXES else "ai"
    )

    def finish(
        status: str,
        message: str,
        request: QuoteRequest | None = None,
        issues: list[Issue] | None = None,
        quote: Quote | None = None,
        pdf_path: Path | None = None,
    ) -> PipelineResult:
        record.status = status
        record.duration_seconds = round(time.perf_counter() - started, 3)
        write_run_record(record, settings.log_dir)
        return PipelineResult(status, message, record, request, issues, quote, pdf_path)

    # 1. Read and extract
    if suffix in FORM_SUFFIXES:
        request = read_form(path, received_at or issue_date)
    elif suffix in EMAIL_SUFFIXES:
        if send is None:
            raise ValueError("an email input needs a Send function (live or replay)")
        text, header_date = read_email(path)
        try:
            extraction = extract(text, header_date or received_at or issue_date, settings, send)
        except ExtractionError as e:
            record.error_reason, record.error_message = e.reason, str(e)
            return finish("failed", f"読み取りに失敗しました（{e.reason}）: {e}")
        request = extraction.request
        record.model = extraction.model
        record.input_tokens, record.output_tokens = (
            extraction.input_tokens,
            extraction.output_tokens,
        )
        cost = estimate_cost_usd(
            extraction.model, extraction.input_tokens, extraction.output_tokens
        )
        record.estimated_cost_usd = f"{cost:.6f}" if cost is not None else None
    else:
        raise ValueError(f"unsupported file type: {path.suffix} (use .txt, .eml or .xlsx)")

    # 2. Validate and review
    issues = validate_request(request, catalog, today=issue_date)
    if reviewer is None:
        if issues:
            _record_request(record, request, issues)
            return finish(
                "needs_review",
                f"警告が{len(issues)}件あるため自動承認（--yes）はできません。"
                "--yes を外して確認してください。",
                request=request,
                issues=issues,
            )
    else:
        result = reviewer(request)
        request, issues = result.request, result.issues
        if not result.approved:
            _record_request(record, request, issues)
            return finish(
                "aborted",
                "中止しました。見積書は作成していません。",
                request=request,
                issues=issues,
            )
    _record_request(record, request, issues)

    # 3. Price and render (deterministic)
    try:
        quote = calculate_quote(request, catalog, rules, issue_date=issue_date)
    except PricingError as e:
        record.error_reason, record.error_message = "pricing", str(e)
        return finish("failed", str(e), request=request, issues=issues)
    pdf = render_quote_pdf(quote, out_dir / f"{quote.quote_number}.pdf")
    record.quote_number, record.total_yen = quote.quote_number, int(quote.total)
    return finish(
        "completed",
        f"見積書を作成しました: {pdf}（合計 {int(quote.total):,}円）",
        request=request,
        issues=issues,
        quote=quote,
        pdf_path=pdf,
    )


def _record_request(record: RunRecord, request: QuoteRequest, issues: list[Issue]) -> None:
    record.company = mask(request.company_name)
    record.contact = mask(request.contact_name)
    record.warning_count = len(issues)
    record.warning_codes = [i.code for i in issues]
