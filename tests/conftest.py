from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from quoteflow.catalog import Catalog
from quoteflow.config import PricingRules, load_pricing_rules
from quoteflow.models import LineItem, QuoteRequest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def catalog() -> Catalog:
    return Catalog.load(ROOT / "data" / "price_list.csv")


@pytest.fixture(scope="session")
def rules() -> PricingRules:
    return load_pricing_rules(ROOT / "config" / "pricing.toml")


@pytest.fixture
def flat_rules() -> PricingRules:
    """Simple round numbers so hand-calculated expectations are easy to read."""
    return PricingRules(
        tax_rate=Decimal("0.10"),
        validity_days=30,
        discount_min_quantity=10,
        discount_rate=Decimal("0.05"),
        express_rate=Decimal("0.10"),
    )


def make_request(*items: tuple[str, int], **overrides: Any) -> QuoteRequest:
    fields: dict[str, Any] = {
        "is_quote_request": True,
        "company_name": "テスト株式会社",
        "contact_name": "山田 太郎",
        "items": [LineItem(product_code=code, quantity=qty) for code, qty in items],
    }
    fields.update(overrides)
    return QuoteRequest(**fields)
