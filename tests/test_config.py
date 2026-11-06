import os
from decimal import Decimal
from pathlib import Path

import pytest

from quoteflow.config import DEFAULT_MODEL, Settings, load_dotenv, load_pricing_rules

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


def test_settings_from_explicit_env() -> None:
    settings = Settings.from_env(
        {
            "QUOTEFLOW_MODEL": "claude-haiku-5-5",
            "QUOTEFLOW_EFFORT": "low",
            "QUOTEFLOW_MAX_RETRIES": "5",
            "QUOTEFLOW_TIMEOUT_SECONDS": "12.5",
            "QUOTEFLOW_REFUSAL_FALLBACK": "false",
            "QUOTEFLOW_LOG_DIR": "/tmp/qf-logs",
        }
    )
    assert settings.model == "claude-haiku-5-5"
    assert settings.effort == "low"
    assert settings.max_retries == 5
    assert settings.timeout_seconds == 12.5
    assert settings.refusal_fallback is False
    assert settings.log_dir == Path("/tmp/qf-logs")


def test_empty_values_fall_back_to_defaults() -> None:
    settings = Settings.from_env({"QUOTEFLOW_MODEL": "", "QUOTEFLOW_MAX_RETRIES": ""})
    assert settings.model == DEFAULT_MODEL
    assert settings.max_retries == 3
    assert settings.refusal_fallback is True


def test_load_dotenv_does_not_override_shell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("QUOTEFLOW_MODEL", "from-shell")
    monkeypatch.delenv("QUOTEFLOW_EFFORT", raising=False)
    monkeypatch.delenv("QUOTEFLOW_LOG_DIR", raising=False)
    env = tmp_path / ".env"
    lines = ["# comment", "QUOTEFLOW_MODEL=from-file", "QUOTEFLOW_EFFORT=low"]
    lines += ["QUOTEFLOW_LOG_DIR=", "not a pair"]
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    load_dotenv(env)
    assert os.environ["QUOTEFLOW_MODEL"] == "from-shell"
    assert os.environ["QUOTEFLOW_EFFORT"] == "low"
    assert "QUOTEFLOW_LOG_DIR" not in os.environ
    load_dotenv(tmp_path / "missing.env")  # no error
