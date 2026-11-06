from datetime import date

import pytest

from quoteflow.normalize import (
    nfkc,
    normalize_code,
    normalize_name,
    normalize_unit,
    parse_quantity,
    resolve_date,
)


def test_nfkc_converts_full_width_to_half_width() -> None:
    assert nfkc("ＢＲＧ－６２０４ＺＺ　１００") == "BRG-6204ZZ 100"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("BRG-6204ZZ", "BRG-6204ZZ"),
        ("brg-6204zz", "BRG-6204ZZ"),
        ("ＴＩＥ－２００－ＮＡＴ", "TIE-200-NAT"),
        (" BRG 6204ZZ ", "BRG6204ZZ"),
        ("BRG‐6204ZZ", "BRG-6204ZZ"),  # U+2010 hyphen
        ("BRG−6204ZZ", "BRG-6204ZZ"),  # U+2212 minus sign
        ("BRGー6204ZZ", "BRG-6204ZZ"),  # katakana long mark typed as a dash
    ],
)
def test_normalize_code(raw: str, expected: str) -> None:
    assert normalize_code(raw) == expected


def test_normalize_name_unifies_spacing_case_and_multiplication_sign() -> None:
    assert normalize_name("六角ボルト M6×20 ステンレス") == normalize_name(
        "六角ボルトm6x20ステンレス"
    )
    assert normalize_name("Oリング P‐20") == "oリングp-20"


def test_normalize_name_keeps_katakana_long_vowel() -> None:
    assert normalize_name("平ワッシャー") == "平ワッシャー"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("個", "個"),
        ("pcs", "個"),
        ("PCS", "個"),
        ("ｍ", "m"),
        ("メートル", "m"),
        ("ケース", "箱"),
        ("巻", "巻"),
        ("ダース", "ダース"),  # unknown units pass through so validation can report them
        ("", None),
        ("  ", None),
        (None, None),
    ],
)
def test_normalize_unit(raw: str | None, expected: str | None) -> None:
    assert normalize_unit(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (5, 5),
        (3.0, 3),
        (2.5, None),
        ("２", 2),
        ("1,000", 1000),
        ("１，０００", 1000),
        (" 30 ", 30),
        ("-5", -5),
        ("三十", None),  # kanji numerals are read by the AI, not here
        ("10個", None),
        ("", None),
        (None, None),
        (True, None),
        ([10], None),
    ],
)
def test_parse_quantity(raw: object, expected: int | None) -> None:
    assert parse_quantity(raw) == expected


RECEIVED = date(2026, 11, 9)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026/12/18", date(2026, 12, 18)),
        ("2026-12-18", date(2026, 12, 18)),
        ("2027年1月5日", date(2027, 1, 5)),
        ("12/18", date(2026, 12, 18)),
        ("１２月１８日", date(2026, 12, 18)),
        ("11/9", date(2026, 11, 9)),  # same day stays in this year
        ("1/25", date(2027, 1, 25)),  # already passed this year -> next year
        ("2/30", None),
        ("2026/13/01", None),
        ("来週", None),
        ("", None),
    ],
)
def test_resolve_date(raw: str, expected: date | None) -> None:
    assert resolve_date(raw, RECEIVED) == expected
