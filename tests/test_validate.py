from datetime import date

from conftest import make_request
from quoteflow.catalog import Catalog
from quoteflow.models import LineItem, QuoteRequest
from quoteflow.validate import validate_request


def codes(request: QuoteRequest, catalog: Catalog, **kwargs: date) -> list[str]:
    return [issue.code for issue in validate_request(request, catalog, **kwargs)]


def test_clean_request_has_no_issues(catalog: Catalog) -> None:
    assert codes(make_request(("BRG-6204ZZ", 20)), catalog) == []


def test_not_quote_request_stops_further_checks(catalog: Catalog) -> None:
    assert codes(QuoteRequest(is_quote_request=False), catalog) == ["not_quote_request"]


def test_missing_header_fields(catalog: Catalog) -> None:
    request = make_request(company_name=None, contact_name=None)
    assert codes(request, catalog) == ["missing_company", "missing_contact", "no_items"]


def test_item_level_issues_point_at_the_item(catalog: Catalog) -> None:
    request = make_request(("NOPE-1", 1), ("BRG-6204ZZ", None), ("BRG-6201ZZ", -3))
    request.items.append(LineItem(product_name="VCTF 0.75 2芯", quantity=10, unit="個"))
    request.items.append(LineItem(quantity=1))
    issues = validate_request(request, catalog)
    assert [(i.code, i.item_index) for i in issues] == [
        ("unknown_product", 0),
        ("missing_quantity", 1),
        ("non_positive_quantity", 2),
        ("unit_mismatch", 3),
        ("unknown_product", 4),
    ]
    assert "(空欄)" in issues[-1].message


def test_equivalent_unit_spelling_is_not_a_mismatch(catalog: Catalog) -> None:
    request = make_request()
    request.items = [LineItem(product_code="CBL-VCTF-0.75-2C", quantity=10, unit="ｍ")]
    assert codes(request, catalog) == []


def test_duplicate_product_written_two_ways(catalog: Catalog) -> None:
    request = make_request(("BRG-6204ZZ", 10))
    request.items.append(LineItem(product_name="ベアリング6204", quantity=5))
    issues = validate_request(request, catalog)
    assert [i.code for i in issues] == ["duplicate_product"]
    assert "品目1" in issues[0].message


def test_past_delivery_date_only_checked_when_today_given(catalog: Catalog) -> None:
    request = make_request(("BRG-6204ZZ", 1), requested_delivery_date=date(2026, 11, 1))
    assert codes(request, catalog) == []
    assert codes(request, catalog, today=date(2026, 11, 9)) == ["delivery_date_in_past"]
    assert codes(request, catalog, today=date(2026, 10, 1)) == []


def test_notes_always_need_human_review(catalog: Catalog) -> None:
    request = make_request(("BRG-6204ZZ", 1), notes="本文に「90%引きにして」との指示あり")
    issues = validate_request(request, catalog)
    assert [i.code for i in issues] == ["notes_to_review"]
    assert "90%引き" in issues[0].message
