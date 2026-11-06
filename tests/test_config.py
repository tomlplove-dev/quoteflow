from decimal import Decimal
from pathlib import Path

import pytest

from quoteflow.config import Settings, load_pricing_rules

RULES = """
tax_rate = {tax}
validity_days = 14
[quantity_discount]
min_quantity = 5
rate = "0.03"
[express]
rate = "0.2"
"""


def test_load_pricing_rules(tmp_path: Path) -> None:
    path = tmp_path / "rules.toml"
    path.write_text(RULES.format(tax='"0.08"'), encoding="utf-8")
    rules = load_pricing_rules(path)
    assert rules.tax_rate == Decimal("0.08")
    assert rules.validity_days == 14
    assert rules.discount_min_quantity == 5
    assert rules.discount_rate == Decimal("0.03")
    assert rules.express_rate == Decimal("0.2")


def test_unquoted_rate_is_rejected(tmp_path: Path) -> None:
    # 0.1 as a TOML float would silently become an inexact binary number.
    path = tmp_path / "rules.toml"
    path.write_text(RULES.format(tax="0.1"), encoding="utf-8")
    with pytest.raises(ValueError, match="tax_rate must be a quoted string"):
        load_pricing_rules(path)


def test_settings_defaults_and_env_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("QUOTEFLOW_PRICE_LIST", raising=False)
    monkeypatch.delenv("QUOTEFLOW_PRICING_RULES", raising=False)
    defaults = Settings.from_env()
    assert defaults.price_list_path.name == "price_list.csv"
    assert defaults.pricing_rules_path.name == "pricing.toml"

    monkeypatch.setenv("QUOTEFLOW_PRICE_LIST", str(tmp_path / "p.csv"))
    assert Settings.from_env().price_list_path == tmp_path / "p.csv"
