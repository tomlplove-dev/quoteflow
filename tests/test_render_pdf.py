from datetime import date
from decimal import Decimal
from pathlib import Path

from conftest import make_request
from quoteflow.catalog import Catalog
from quoteflow.config import PricingRules
from quoteflow.models import Quote
from quoteflow.pricing import calculate_quote
from quoteflow.render_pdf import render_quote_pdf, yen


def make_quote(catalog: Catalog, rules: PricingRules, **overrides: object) -> Quote:
    request = make_request(("BRG-6204ZZ", 20), ("NUT-M8-SUS", 200), **overrides)
    return calculate_quote(
        request, catalog, rules, issue_date=date(2026, 11, 9), quote_number="Q-T"
    )


def test_yen_format() -> None:
    assert yen(Decimal("19437")) == "19,437円"
    assert yen(Decimal("0")) == "0円"


def test_pdf_is_written(tmp_path: Path, catalog: Catalog, rules: PricingRules) -> None:
    path = render_quote_pdf(make_quote(catalog, rules), tmp_path / "sub" / "q.pdf")
    data = path.read_bytes()
    assert data.startswith(b"%PDF-")
    assert b"/Type /Page" in data
    assert b"HeiseiKakuGo-W5" in data


def test_same_quote_gives_byte_identical_pdf(
    tmp_path: Path, catalog: Catalog, rules: PricingRules
) -> None:
    quote = make_quote(catalog, rules)
    a = render_quote_pdf(quote, tmp_path / "a.pdf").read_bytes()
    b = render_quote_pdf(quote, tmp_path / "b.pdf").read_bytes()
    assert a == b


def test_different_quote_gives_different_pdf(
    tmp_path: Path, catalog: Catalog, rules: PricingRules
) -> None:
    a = render_quote_pdf(make_quote(catalog, rules), tmp_path / "a.pdf").read_bytes()
    b = render_quote_pdf(make_quote(catalog, rules, express=True), tmp_path / "b.pdf").read_bytes()
    assert a != b


def test_renders_without_contact_or_delivery_and_escapes_markup(
    tmp_path: Path, catalog: Catalog, rules: PricingRules
) -> None:
    quote = make_quote(
        catalog,
        rules,
        company_name="<b>株式会社 A&B</b>",
        contact_name=None,
        requested_delivery_date=None,
    )
    assert render_quote_pdf(quote, tmp_path / "q.pdf").exists()


def test_renders_with_delivery_date(tmp_path: Path, catalog: Catalog, rules: PricingRules) -> None:
    quote = make_quote(catalog, rules, requested_delivery_date=date(2026, 12, 10), express=True)
    assert render_quote_pdf(quote, tmp_path / "q.pdf").exists()
