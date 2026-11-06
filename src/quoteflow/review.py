"""Human review in the terminal: approve, edit or abort. Nothing is priced before approval.

Input/output functions are passed in (ask / edit / echo), so the same logic runs with
typer in the CLI and with plain functions in tests.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from pydantic import ValidationError

from quoteflow.catalog import Catalog
from quoteflow.models import QuoteRequest
from quoteflow.validate import BLOCKING_CODES, Issue, validate_request

Ask = Callable[[str], str]
Edit = Callable[[str], str | None]
Echo = Callable[[str], None]


@dataclass(frozen=True)
class ReviewResult:
    approved: bool
    request: QuoteRequest
    issues: list[Issue]


def format_request(request: QuoteRequest, catalog: Catalog) -> str:
    """The extracted request as the reviewer sees it, including how each item matched."""
    lines = [
        f"見積依頼: {'はい' if request.is_quote_request else 'いいえ'}",
        f"会社名:   {request.company_name or '(なし)'}",
        f"担当者:   {request.contact_name or '(なし)'}",
        f"希望納期: {request.requested_delivery_date or '(指定なし)'}",
        f"特急:     {'あり' if request.express else 'なし'}",
        "品目:",
    ]
    for i, item in enumerate(request.items, start=1):
        written = " / ".join(t for t in (item.product_code, item.product_name) if t) or "(空欄)"
        product = catalog.match(item).product
        matched = f"{product.code} {product.name}" if product else "?? 価格表にありません"
        qty = f"{item.quantity}{item.unit or ''}" if item.quantity is not None else "?"
        lines.append(f"  {i}. {written}  ->  {matched}  x {qty}")
    if not request.items:
        lines.append("  (なし)")
    if request.notes:
        lines.append(f"備考:     {request.notes}")
    return "\n".join(lines)


def format_issues(issues: list[Issue]) -> str:
    if not issues:
        return "警告: なし"
    marks = ["  [要修正] " if i.code in BLOCKING_CODES else "  [確認]   " for i in issues]
    return "警告:\n" + "\n".join(mark + i.message for mark, i in zip(marks, issues, strict=True))


def review(
    request: QuoteRequest,
    catalog: Catalog,
    *,
    today: date,
    ask: Ask,
    edit: Edit,
    echo: Echo,
) -> ReviewResult:
    while True:
        issues = validate_request(request, catalog, today=today)
        echo(format_request(request, catalog))
        echo(format_issues(issues))
        choice = ask("[a] 承認 / [e] 修正 / [q] 中止").strip().lower()

        if choice == "a":
            if any(i.code in BLOCKING_CODES for i in issues):
                echo("[要修正] の項目があるため承認できません。修正するか中止してください。")
                continue
            return ReviewResult(approved=True, request=request, issues=issues)
        if choice == "q":
            return ReviewResult(approved=False, request=request, issues=issues)
        if choice == "e":
            edited = edit(request.model_dump_json(indent=2))
            if edited is None:
                echo("変更はありません。")
                continue
            try:
                request = QuoteRequest.model_validate_json(edited)
            except ValidationError as e:
                echo(
                    f"JSONの形式が正しくありません（{e.error_count()}件）。変更は反映していません。"
                )
            continue
        echo("a / e / q のいずれかを入力してください。")
