"""One JSON line per processed request: timing, tokens, estimated cost, warnings.

Personal data never reaches the log in clear text. Company and contact names are replaced
by a short hash, so runs for the same customer can still be grouped without storing who
they are. Email addresses are masked anywhere in free text.
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path

# USD per million tokens (input, output), from the official price list (checked 2026-11).
MODEL_PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "claude-opus-5-5": (Decimal("4.00"), Decimal("20.00")),
    "claude-sonnet-5-5": (Decimal("2.00"), Decimal("10.00")),
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50")),
}

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def estimate_cost_usd(model: str | None, input_tokens: int, output_tokens: int) -> Decimal | None:
    """Estimated API cost, or None for a model without a known price."""
    if model is None or model not in MODEL_PRICES:
        return None
    input_price, output_price = MODEL_PRICES[model]
    return (input_price * input_tokens + output_price * output_tokens) / Decimal(1_000_000)


def mask(value: str | None) -> str | None:
    """Replace a name with a stable, non-reversible tag such as '#3f9a1c'."""
    if not value:
        return None
    return "#" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:6]


def mask_emails(text: str) -> str:
    return _EMAIL.sub("***@***", text)


@dataclass
class RunRecord:
    source_file: str
    status: str  # completed | aborted | needs_review | failed
    mode: str  # ai | form
    model: str | None = None
    duration_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: str | None = None
    warning_count: int = 0
    warning_codes: list[str] = field(default_factory=list)
    company: str | None = None  # masked
    contact: str | None = None  # masked
    quote_number: str | None = None
    total_yen: int | None = None
    error_reason: str | None = None
    error_message: str | None = None


def write_run_record(record: RunRecord, log_dir: Path) -> Path:
    """Append the record to <log_dir>/runs.jsonl and return the file path."""
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "runs.jsonl"
    data = asdict(record)
    if record.error_message:
        data["error_message"] = mask_emails(record.error_message)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")
    return path
