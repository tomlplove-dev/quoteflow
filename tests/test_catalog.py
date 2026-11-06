from decimal import Decimal
from pathlib import Path

import pytest

from quoteflow.catalog import Catalog, CatalogError, Product
from quoteflow.models import LineItem

HEADER = "product_code,name,aliases,unit,unit_price,category\n"


def test_load_reads_all_products(catalog: Catalog) -> None:
    assert len(catalog.products) == 26
    bearing = catalog.get("BRG-6204ZZ")
    assert bearing is not None
    assert bearing.unit_price == Decimal("520")
    assert bearing.aliases == ("6204ZZ", "ベアリング6204")


def test_get_normalises_code(catalog: Catalog) -> None:
    assert catalog.get("ｂｒｇ－６２０４ｚｚ") == catalog.get("BRG-6204ZZ")
    assert catalog.get("NOPE-1") is None


@pytest.mark.parametrize(
    ("item", "code", "method"),
    [
        (LineItem(product_code="BRG-6204ZZ"), "BRG-6204ZZ", "code"),
        (LineItem(product_code="ＴＩＥ－２００－ＮＡＴ"), "TIE-200-NAT", "code"),
        (LineItem(product_name="深溝玉軸受 6204ZZ"), "BRG-6204ZZ", "name"),
        (LineItem(product_name="M10x40 ユニクロ"), "BLT-M10-40-ZN", "alias"),
        (LineItem(product_name="BRG-6204ZZ"), "BRG-6204ZZ", "code"),  # code in the name column
        (LineItem(product_code="黒ビニテ"), "TAP-PVC-19-BK", "alias"),  # alias in the code column
        (LineItem(product_code="WRONG", product_name="6204ZZ"), "BRG-6204ZZ", "alias"),
    ],
)
def test_match(catalog: Catalog, item: LineItem, code: str, method: str) -> None:
    result = catalog.match(item)
    assert result.product is not None
    assert result.product.code == code
    assert result.method == method


def test_match_does_not_guess_typos(catalog: Catalog) -> None:
    result = catalog.match(LineItem(product_name="ベアリンク6204"))
    assert result.product is None
    assert result.method is None


def test_match_empty_item(catalog: Catalog) -> None:
    assert catalog.match(LineItem()).product is None
    assert catalog.match(LineItem(product_code="  ")).product is None


def test_search_finds_typo_candidates(catalog: Catalog) -> None:
    results = catalog.search("ベアリンク6204", limit=3)
    assert results[0][0].code == "BRG-6204ZZ"
    assert len(results) == 3
    assert results[0][1] >= results[1][1]


def test_duplicate_alias_is_rejected() -> None:
    a = Product("A-1", "部品A", ("共通名",), "個", Decimal(1), "x")
    b = Product("B-1", "部品B", ("共通名",), "個", Decimal(1), "x")
    with pytest.raises(CatalogError, match="共通名"):
        Catalog([a, b])


def test_duplicate_code_is_rejected() -> None:
    a = Product("A-1", "部品A", (), "個", Decimal(1), "x")
    b = Product("a-1", "部品B", (), "個", Decimal(1), "x")
    with pytest.raises(CatalogError):
        Catalog([a, b])


@pytest.mark.parametrize("price", ["abc", "-1"])
def test_load_rejects_bad_price(tmp_path: Path, price: str) -> None:
    path = tmp_path / "prices.csv"
    path.write_text(HEADER + f"X-1,部品,,個,{price},x\n", encoding="utf-8")
    with pytest.raises(CatalogError, match=":2:"):
        Catalog.load(path)
