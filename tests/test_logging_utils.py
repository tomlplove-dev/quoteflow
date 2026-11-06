import json
from decimal import Decimal
from pathlib import Path

from quoteflow.logging_utils import (
    RunRecord,
    estimate_cost_usd,
    mask,
    mask_emails,
    write_run_record,
)


def test_cost_estimate() -> None:
    assert estimate_cost_usd("claude-opus-5-5", 1_000_000, 0) == Decimal("4")
    assert estimate_cost_usd("claude-haiku-5-5", 2000, 1000) == Decimal("0.0007")
    assert estimate_cost_usd("unknown-model", 10, 10) is None
    assert estimate_cost_usd(None, 10, 10) is None


def test_mask_is_stable_and_hides_the_value() -> None:
    assert mask("ミナモ機工株式会社") == mask("ミナモ機工株式会社")
    assert mask("ミナモ機工株式会社") != mask("株式会社ソラノ製作所")
    tag = mask("佐藤 健一")
    assert tag is not None and tag.startswith("#") and "佐藤" not in tag
    assert mask(None) is None
    assert mask("") is None


def test_mask_emails() -> None:
    assert mask_emails("from k.sato@minamo-kiko.example today") == "from ***@*** today"


def test_write_run_record_appends_and_masks_messages(tmp_path: Path) -> None:
    record = RunRecord(
        source_file="a.txt", status="failed", mode="ai", error_message="bad x@y.example"
    )
    path = write_run_record(record, tmp_path / "logs")
    write_run_record(
        RunRecord(source_file="b.txt", status="completed", mode="form"), tmp_path / "logs"
    )
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [line["source_file"] for line in lines] == ["a.txt", "b.txt"]
    assert lines[0]["error_message"] == "bad ***@***"
