"""Reading request files: email text (.txt / .eml) and the Excel request form (.xlsx).

Free-text email goes to Claude. The Excel form already has fixed cells, so it is read by
code - no AI, no cost, no extraction error to evaluate. Blank cells and spelling variants
are left for normalize/catalog/validate to handle, exactly like extracted data.
"""

import email
import email.policy
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from pathlib import Path

from openpyxl import load_workbook

from quoteflow.models import LineItem, QuoteRequest
from quoteflow.normalize import nfkc, parse_quantity, resolve_date

EMAIL_SUFFIXES = {".txt", ".eml"}
FORM_SUFFIXES = {".xlsx"}

_HEADER_LABELS = {
    "会社名": "company",
    "ご担当者": "contact",
    "希望納期": "delivery",
    "特急": "express",
}
_YES = {"有", "あり", "要", "○", "〇", "yes", "y", "true", "1"}


def read_email(path: Path) -> tuple[str, date | None]:
    """Return (text for the model, received date if the file says so).

    .txt files have no reliable date; .eml files carry it in the Date header.
    """
    if path.suffix.lower() == ".txt":
        return path.read_text(encoding="utf-8"), None

    msg = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
    assert isinstance(msg, EmailMessage)
    body = msg.get_body(preferencelist=("plain",))
    text = body.get_content() if body is not None else ""
    header = f"件名: {msg.get('Subject', '')}\n差出人: {msg.get('From', '')}\n\n"
    received = parsedate_to_datetime(msg["Date"]).date() if msg["Date"] else None
    return header + text, received


def _cell_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _form_date(value: object, received_at: date) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _cell_text(value)
    return resolve_date(text, received_at) if text else None


def read_form(path: Path, received_at: date) -> QuoteRequest:
    """Read the customer's Excel request form into a QuoteRequest."""
    workbook = load_workbook(path, read_only=True, data_only=True)
    rows = [list(r) for r in workbook.worksheets[0].iter_rows(values_only=True)]
    workbook.close()

    header: dict[str, object] = {}
    table_start = None
    for i, row in enumerate(rows):
        label = _cell_text(row[0]) if row else None
        if label in _HEADER_LABELS and len(row) > 1:
            header[_HEADER_LABELS[label]] = row[1]
        if "品番" in row and "数量" in row:
            table_start = i
            break

    items: list[LineItem] = []
    notes: list[str] = []
    if table_start is not None:
        columns = {
            name: rows[table_start].index(name)
            for name in ("品番", "品名", "数量", "単位", "備考")
            if name in rows[table_start]
        }

        def cell(row: list[object], name: str) -> object:
            index = columns.get(name)
            return row[index] if index is not None and index < len(row) else None

        for row in rows[table_start + 1 :]:
            code, name, qty = cell(row, "品番"), cell(row, "品名"), cell(row, "数量")
            if all(_cell_text(v) is None for v in (code, name, qty)):
                continue  # blank line inside the table
            items.append(
                LineItem(
                    product_code=_cell_text(code),
                    product_name=_cell_text(name),
                    quantity=parse_quantity(qty),
                    unit=_cell_text(cell(row, "単位")),
                )
            )
            remark = _cell_text(cell(row, "備考"))
            if remark:
                notes.append(f"品目{len(items)}: {remark}")

    delivery_raw = header.get("delivery")
    delivery = _form_date(delivery_raw, received_at)
    if delivery_raw is not None and delivery is None:
        notes.append(f"希望納期を読み取れません: {delivery_raw}")
    express_text = _cell_text(header.get("express"))

    return QuoteRequest(
        is_quote_request=True,
        company_name=_cell_text(header.get("company")),
        contact_name=_cell_text(header.get("contact")),
        items=items,
        requested_delivery_date=delivery,
        express=bool(express_text) and nfkc(express_text or "").lower() in _YES,
        notes=" / ".join(notes) or None,
    )
