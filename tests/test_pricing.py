"""Money must be exact. Expected values below are calculated by hand."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from conftest import ROOT, make_request
from quoteflow.catalog import Catalog
from quoteflow.config import PricingRules
from quoteflow.models import LineItem, QuoteRequest
from quoteflow.pricing import PricingError, calculate_quote, floor_yen, make_quote_number

ISSUE = date(2026, 11, 9)


@pytest.mark.parametrize(
    ("amount", "expected"),
    [("11.7", "11"), ("11.0", "11"), ("0.99", "0"), ("1767.0", "1767"), ("1999.999", "1999")],
)
def test_floor_yen_always_rounds_down(amount: str, expected: str) -> None:
    assert floor_yen(Decimal(amount)) == Decimal(expected)


def test_simple_quote_below_discount_threshold(catalog: Catalog, flat_rules: PricingRules) -> None:
    # 6204ZZ: 520 x 9 = 4,680, no discount (9 < 10). Tax 468.
    quote = calculate_quote(make_request(("BRG-6204ZZ", 9)), catalog, flat_rules, issue_date=ISSUE)
    assert quote.subtotal == Decimal("4680")
    assert quote.discount_total == 0
    assert quote.express_fee == 0
    assert quote.tax == Decimal("468")
    assert quote.total == Decimal("5148")


def test_discount_applies_at_threshold(catalog: Catalog, flat_rules: PricingRules) -> None:
    # 520 x 10 = 5,200; 5% = 260; taxable 4,940; tax 494.
    quote = calculate_quote(make_request(("BRG-6204ZZ", 10)), catalog, flat_rules, issue_date=ISSUE)
    assert quote.lines[0].discount == Decimal("260")
    assert quote.total == Decimal("5434")


def test_line_discount_is_rounded_down(catalog: Catalog, flat_rules: PricingRules) -> None:
    # M6 bolt 18 x 13 = 234; 5% = 11.7 -> 11.
    quote = calculate_quote(
        make_request(("BLT-M6-20-SUS", 13)), catalog, flat_rules, issue_date=ISSUE
    )
    assert quote.lines[0].discount == Decimal("11")


def test_express_fee_is_ten_percent_of_subtotal(catalog: Catalog, flat_rules: PricingRules) -> None:
    # 6305DDU 1,350 x 3 = 4,050; express 405; taxable 4,455; tax 445.5 -> 445.
    request = make_request(("BRG-6305DDU", 3), express=True)
    quote = calculate_quote(request, catalog, flat_rules, issue_date=ISSUE)
    assert quote.express_fee == Decimal("405")
    assert quote.tax == Decimal("445")
    assert quote.total == Decimal("4900")


def test_tax_is_calculated_once_on_the_whole_quote(
    catalog: Catalog, flat_rules: PricingRules
) -> None:
    # Per-line tax would be floor(1.8)+floor(0.6) = 1; per-quote is floor(2.4) = 2.
    request = make_request(("BLT-M6-20-SUS", 1), ("NUT-M6-SUS", 1))
    quote = calculate_quote(request, catalog, flat_rules, issue_date=ISSUE)
    assert quote.tax == Decimal("2")


def test_quote_dates_and_number(catalog: Catalog, flat_rules: PricingRules) -> None:
    request = make_request(("BRG-6204ZZ", 1))
    quote = calculate_quote(request, catalog, flat_rules, issue_date=ISSUE)
    assert quote.valid_until == date(2026, 12, 9)
    assert quote.quote_number == make_quote_number(request, ISSUE)
    assert quote.quote_number.startswith("Q-20261109-")
    custom = calculate_quote(request, catalog, flat_rules, issue_date=ISSUE, quote_number="Q-1")
    assert custom.quote_number == "Q-1"


def test_quote_number_depends_on_content() -> None:
    a, b = make_request(("BRG-6204ZZ", 1)), make_request(("BRG-6204ZZ", 2))
    assert make_quote_number(a, ISSUE) == make_quote_number(a, ISSUE)
    assert make_quote_number(a, ISSUE) != make_quote_number(b, ISSUE)


def test_same_input_gives_same_quote(catalog: Catalog, rules: PricingRules) -> None:
    request = make_request(("BRG-6204ZZ", 20), ("NUT-M8-SUS", 200), express=True)
    first = calculate_quote(request, catalog, rules, issue_date=ISSUE)
    second = calculate_quote(request, catalog, rules, issue_date=ISSUE)
    assert first == second


def test_name_and_unit_variants_are_priced(catalog: Catalog, flat_rules: PricingRules) -> None:
    request = make_request()
    request.items = [LineItem(product_name="M10x40 ユニクロ", quantity=100, unit="pcs")]
    quote = calculate_quote(request, catalog, flat_rules, issue_date=ISSUE)
    assert quote.lines[0].product_code == "BLT-M10-40-ZN"


def test_every_problem_is_reported_at_once(catalog: Catalog, flat_rules: PricingRules) -> None:
    request = make_request(("NOPE-1", 1), ("BRG-6204ZZ", 0))
    request.items.append(LineItem(product_code="CBL-VCTF-0.75-2C", quantity=10, unit="個"))
    with pytest.raises(PricingError) as err:
        calculate_quote(request, catalog, flat_rules, issue_date=ISSUE)
    message = str(err.value)
    assert "品目1: 価格表にない商品" in message
    assert "品目2: 数量が正しくありません" in message
    assert "品目3: 単位が価格表と違います" in message


@pytest.mark.parametrize(
    ("request_", "fragment"),
    [
        (QuoteRequest(is_quote_request=False), "見積依頼ではありません"),
        (make_request(("BRG-6204ZZ", 1), company_name=None), "会社名がありません"),
        (make_request(), "品目がありません"),
        (make_request(("BRG-6204ZZ", None)), "数量が正しくありません"),
    ],
)
def test_request_level_problems(
    catalog: Catalog, flat_rules: PricingRules, request_: QuoteRequest, fragment: str
) -> None:
    with pytest.raises(PricingError, match=fragment):
        calculate_quote(request_, catalog, flat_rules, issue_date=ISSUE)


# Totals for the demo samples, checked by hand once and pinned here.
SAMPLE_TOTALS = {
    "request_01": "19437",
    "request_02": "25844",
    "request_03": "11968",
    "request_04_injection": "25132",
}


@pytest.mark.parametrize(("name", "total"), SAMPLE_TOTALS.items())
def test_sample_totals(catalog: Catalog, rules: PricingRules, name: str, total: str) -> None:
    path = ROOT / "data" / "samples" / f"{name}.expected.json"
    request = QuoteRequest.model_validate_json(path.read_text(encoding="utf-8"))
    quote = calculate_quote(request, catalog, rules, issue_date=ISSUE)
    assert quote.total == Decimal(total)
    assert quote.total == quote.subtotal - quote.discount_total + quote.express_fee + quote.tax


def test_every_eval_ground_truth_can_be_priced(catalog: Catalog, rules: PricingRules) -> None:
    """If extraction is right, pricing never fails: the ground truth is always priceable."""
    lines = (ROOT / "data" / "eval" / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    priced = 0
    for line in lines:
        case = json.loads(line)
        request = QuoteRequest.model_validate(case["expected"])
        if request.is_quote_request:
            calculate_quote(request, catalog, rules, issue_date=ISSUE)
            priced += 1
    assert priced >= 35


def test_rules_file_is_loaded(rules: PricingRules) -> None:
    assert rules.tax_rate == Decimal("0.10")
    assert rules.discount_min_quantity == 10
    assert Path(ROOT / "config" / "pricing.toml").exists()
