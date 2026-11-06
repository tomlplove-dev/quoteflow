"""The committed synthetic data must be reproducible from the seed and internally consistent."""

import csv
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SCRIPT = ROOT / "scripts" / "make_synthetic_data.py"


def load_cases() -> list[dict[str, Any]]:
    lines = (DATA / "eval" / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def load_price_list() -> dict[str, dict[str, str]]:
    with (DATA / "price_list.csv").open(encoding="utf-8", newline="") as f:
        return {row["product_code"]: row for row in csv.DictReader(f)}


def test_regeneration_is_byte_identical(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, str(SCRIPT), "--out", str(tmp_path)], check=True, capture_output=True
    )
    generated = sorted(p for p in tmp_path.rglob("*") if p.is_file())
    assert generated, "generator wrote no files"
    for path in generated:
        rel = path.relative_to(tmp_path)
        committed = DATA / rel
        assert committed.exists(), f"{rel} is generated but not committed"
        assert path.read_bytes() == committed.read_bytes(), f"{rel} differs from committed data"


def test_eval_set_has_required_mix() -> None:
    cases = load_cases()
    counts = Counter(c["category"] for c in cases)
    assert len(cases) >= 40
    assert counts["typical"] >= 20
    assert counts["hard"] >= 10
    assert counts["non_quote"] + counts["injection"] >= 5
    assert len({c["id"] for c in cases}) == len(cases), "case ids must be unique"


def test_expected_items_exist_in_price_list() -> None:
    prices = load_price_list()
    sample_truths = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in (DATA / "samples").glob("*.expected.json")
    ]
    truths = [c["expected"] for c in load_cases()] + sample_truths
    for truth in truths:
        for item in truth["items"]:
            assert item["product_code"] in prices
            assert item["unit"] == prices[item["product_code"]]["unit"]
            assert isinstance(item["quantity"], int) and item["quantity"] > 0


def test_non_quote_cases_expect_no_items() -> None:
    for c in load_cases():
        if not c["expected"]["is_quote_request"]:
            assert c["expected"]["items"] == []


def test_injection_cases_keep_normal_ground_truth() -> None:
    injections = [c for c in load_cases() if c["category"] == "injection"]
    assert injections
    for c in injections:
        assert c["injection"]["instruction"] in c["email_text"]
        assert c["expected"]["is_quote_request"] is True
        assert c["expected"]["items"]


def test_every_sample_has_ground_truth() -> None:
    samples = [p for p in (DATA / "samples").iterdir() if p.suffix in {".txt", ".eml", ".xlsx"}]
    assert {".txt", ".eml", ".xlsx"} <= {p.suffix for p in samples}
    for p in samples:
        assert p.with_name(f"{p.stem}.expected.json").exists(), p.name


def test_only_reserved_example_email_domains() -> None:
    """No real-looking addresses: every email in data/ must use the reserved .example TLD."""
    pattern = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
    for path in DATA.rglob("*"):
        if path.is_file() and path.suffix in {".txt", ".eml", ".jsonl", ".json", ".csv"}:
            for domain in pattern.findall(path.read_text(encoding="utf-8")):
                assert domain.endswith(".example"), f"{path.name}: {domain}"
