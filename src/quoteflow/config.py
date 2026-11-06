"""Settings from environment variables and the pricing rules file.

Every path can be overridden with an environment variable so the customer can point
QuoteFlow at their own price list without touching code.
"""

import os
import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class PricingRules(BaseModel):
    tax_rate: Decimal
    validity_days: int
    discount_min_quantity: int
    discount_rate: Decimal
    express_rate: Decimal


@dataclass(frozen=True)
class Settings:
    price_list_path: Path
    pricing_rules_path: Path

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            price_list_path=Path(
                os.environ.get("QUOTEFLOW_PRICE_LIST", PROJECT_ROOT / "data" / "price_list.csv")
            ),
            pricing_rules_path=Path(
                os.environ.get("QUOTEFLOW_PRICING_RULES", PROJECT_ROOT / "config" / "pricing.toml")
            ),
        )


def load_pricing_rules(path: Path) -> PricingRules:
    """Read the TOML rules file. Rates must be strings so they become exact Decimals."""
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    for key, value in [
        ("tax_rate", raw["tax_rate"]),
        ("quantity_discount.rate", raw["quantity_discount"]["rate"]),
        ("express.rate", raw["express"]["rate"]),
    ]:
        if not isinstance(value, str):
            raise ValueError(f'{path}: {key} must be a quoted string like "0.10", got {value!r}')
    return PricingRules(
        tax_rate=Decimal(raw["tax_rate"]),
        validity_days=raw["validity_days"],
        discount_min_quantity=raw["quantity_discount"]["min_quantity"],
        discount_rate=Decimal(raw["quantity_discount"]["rate"]),
        express_rate=Decimal(raw["express"]["rate"]),
    )
