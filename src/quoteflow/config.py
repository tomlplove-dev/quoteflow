"""Settings from environment variables (optionally a .env file) and the pricing rules file.

Every setting can be changed without touching code, so the customer can point QuoteFlow
at their own price list or switch models during evaluation.
"""

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Default extraction model. Checked against the official model list (2026-11);
# compare with a lighter model, e.g. QUOTEFLOW_MODEL=claude-haiku-5-5, in the evaluation.
DEFAULT_MODEL = "claude-opus-5-5"


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
    model: str = DEFAULT_MODEL
    effort: str = "medium"
    max_tokens: int = 16000
    max_retries: int = 3  # SDK retries connection errors, 408, 409, 429 and 5xx with backoff
    timeout_seconds: float = 60.0  # per attempt
    refusal_fallback: bool = True
    log_dir: Path = PROJECT_ROOT / "logs"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        return cls(
            price_list_path=Path(
                env.get("QUOTEFLOW_PRICE_LIST", PROJECT_ROOT / "data" / "price_list.csv")
            ),
            pricing_rules_path=Path(
                env.get("QUOTEFLOW_PRICING_RULES", PROJECT_ROOT / "config" / "pricing.toml")
            ),
            model=env.get("QUOTEFLOW_MODEL") or DEFAULT_MODEL,
            effort=env.get("QUOTEFLOW_EFFORT") or "medium",
            max_tokens=int(env.get("QUOTEFLOW_MAX_TOKENS") or 16000),
            max_retries=int(env.get("QUOTEFLOW_MAX_RETRIES") or 3),
            timeout_seconds=float(env.get("QUOTEFLOW_TIMEOUT_SECONDS") or 60),
            refusal_fallback=(env.get("QUOTEFLOW_REFUSAL_FALLBACK") or "true").lower() == "true",
            log_dir=Path(env.get("QUOTEFLOW_LOG_DIR") or PROJECT_ROOT / "logs"),
        )


def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines from a .env file. Variables already set in the shell win.

    Deliberately minimal (no quoting rules, no interpolation) to avoid another dependency.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if value.strip():
            os.environ.setdefault(key.strip(), value.strip())


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
