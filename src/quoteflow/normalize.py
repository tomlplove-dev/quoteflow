"""Normalisation of the spelling variations customers use (full-width, dashes, units).

All functions are pure and deterministic. They only change *how* something is written,
never *what* it means - e.g. "ＴＩＥ－２００" becomes "TIE-200", but a typo stays a typo.
"""

import re
import unicodedata
from datetime import date

# Dash-like characters customers type instead of "-". The katakana long-vowel mark "ー"
# is included for product codes only: in names it is part of words such as "ワッシャー".
_CODE_DASHES = "‐‑‒–—―−ー"
_NAME_DASHES = "‐‑‒–—―−"

_UNIT_ALIASES = {
    "個": "個",
    "コ": "個",
    "ヶ": "個",
    "pc": "個",
    "pcs": "個",
    "本": "本",
    "m": "m",
    "メートル": "m",
    "箱": "箱",
    "ケース": "箱",
    "巻": "巻",
    "ロール": "巻",
}


def nfkc(text: str) -> str:
    """Unicode NFKC: full-width letters/digits/symbols become half-width (１００ -> 100)."""
    return unicodedata.normalize("NFKC", text)


def normalize_code(code: str) -> str:
    """Canonical form of a product code: half-width, upper case, '-' dashes, no spaces."""
    text = nfkc(code).upper()
    text = re.sub(f"[{_CODE_DASHES}]", "-", text)
    return re.sub(r"\s+", "", text)


def normalize_name(name: str) -> str:
    """Canonical form of a product name or alias, used as a lookup key."""
    text = nfkc(name).lower()
    text = text.replace("×", "x").replace("*", "x")
    text = re.sub(f"[{_NAME_DASHES}]", "-", text)
    return re.sub(r"\s+", "", text)


def normalize_unit(unit: str | None) -> str | None:
    """Map unit spellings to the price-list unit ('ｍ' -> 'm', 'pcs' -> '個').

    Unknown units are returned in NFKC form so the validator can report them.
    """
    if unit is None or not unit.strip():
        return None
    key = nfkc(unit).strip().lower()
    return _UNIT_ALIASES.get(key, key)


def parse_quantity(value: object) -> int | None:
    """Parse a quantity from a spreadsheet cell or text ('２', '1,000', 3.0).

    Returns None when the value is empty or not a whole number. Negative numbers are
    returned as-is so the validator can flag them rather than silently dropping them.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        text = nfkc(value).replace(",", "").strip()
        return int(text) if re.fullmatch(r"-?\d+", text) else None
    return None


def resolve_date(text: str, received_at: date) -> date | None:
    """Parse '2026/12/18', '2026-12-18', '12/18', '12月18日', '2026年12月18日'.

    A date without a year means the first such date on or after `received_at`
    (a request received in November for "1/25" means next January).
    Returns None for anything else, including impossible dates.
    """
    t = nfkc(text).strip()
    full = re.fullmatch(r"(\d{4})[/\-年](\d{1,2})[/\-月](\d{1,2})日?", t)
    short = re.fullmatch(r"(\d{1,2})[/月](\d{1,2})日?", t)
    try:
        if full:
            return date(int(full[1]), int(full[2]), int(full[3]))
        if short:
            month, day = int(short[1]), int(short[2])
            candidate = date(received_at.year, month, day)
            return candidate if candidate >= received_at else date(received_at.year + 1, month, day)
    except ValueError:
        return None
    return None
