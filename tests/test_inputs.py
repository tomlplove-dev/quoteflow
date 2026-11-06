from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook

from conftest import ROOT
from quoteflow.inputs import read_email, read_form

SAMPLES = ROOT / "data" / "samples"
RECEIVED = date(2026, 11, 9)


def test_read_txt_has_no_date() -> None:
    text, received = read_email(SAMPLES / "request_01.txt")
    assert "深溝玉軸受 6204ZZ" in text
    assert received is None


def test_read_eml_uses_headers_and_body() -> None:
    text, received = read_email(SAMPLES / "request_03.eml")
    assert received == date(2026, 11, 9)
    assert text.startswith("件名: 【至急】見積依頼\n差出人: 鈴木 美咲")
    assert "Oリング P-20 × 100個" in text


def test_read_sample_form() -> None:
    request = read_form(SAMPLES / "request_02.xlsx", RECEIVED)
    assert request.is_quote_request
    assert request.company_name == "ユキミ設備株式会社"
    assert request.contact_name == "伊藤 翔太"
    assert request.requested_delivery_date == date(2026, 12, 18)
    assert request.express is False
    assert [(i.product_code, i.product_name, i.quantity, i.unit) for i in request.items] == [
        ("BLT-ANC-M10", "アンカーボルト M10", 40, "本"),
        (None, "M10x40 ユニクロ", 100, "個"),
        ("ＴＩＥ－２００－ＮＡＴ", None, 2, None),  # blank row skipped, full-width kept as written
        ("SHF-SUS-10-300", "ステンレスシャフト φ10×300", 6, "本"),
    ]
    assert request.notes == "品目2: 品番不明 / 品目4: 端面処理なし"


def write_form(path: Path, header: list[tuple[str, object]], rows: list[list[object]]) -> Path:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    for label, value in header:
        ws.append([label, value])
    ws.append(["No", "品番", "数量"])  # minimal table: no name / unit / remarks columns
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


def test_form_with_date_cell_and_express(tmp_path: Path) -> None:
    header = [("会社名", "テスト株式会社"), ("希望納期", datetime(2027, 1, 15)), ("特急", "有")]
    request = read_form(write_form(tmp_path / "f.xlsx", header, [[1, "BRG-6204ZZ", 3]]), RECEIVED)
    assert request.requested_delivery_date == date(2027, 1, 15)
    assert request.express is True
    assert request.contact_name is None
    assert request.items[0].product_name is None
    assert request.notes is None


def test_form_with_unreadable_date_goes_to_notes(tmp_path: Path) -> None:
    header = [("会社名", "テスト株式会社"), ("希望納期", "なるべく早く"), ("特急", "無")]
    request = read_form(write_form(tmp_path / "f.xlsx", header, []), RECEIVED)
    assert request.requested_delivery_date is None
    assert request.express is False
    assert request.items == []
    assert request.notes == "希望納期を読み取れません: なるべく早く"


def test_form_with_date_object(tmp_path: Path) -> None:
    header = [("希望納期", date(2026, 12, 1))]
    request = read_form(write_form(tmp_path / "f.xlsx", header, []), RECEIVED)
    assert request.requested_delivery_date == date(2026, 12, 1)


def test_sheet_without_table(tmp_path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["会社名", "テスト株式会社"])
    ws.append([])
    wb.save(tmp_path / "f.xlsx")
    request = read_form(tmp_path / "f.xlsx", RECEIVED)
    assert request.company_name == "テスト株式会社"
    assert request.items == []
