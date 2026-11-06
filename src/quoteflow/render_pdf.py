"""Quote PDF rendering with reportlab. Layout is code, so the same Quote gives the same PDF.

`invariant=1` makes reportlab write a fixed creation date and document ID, so two renders
of the same Quote are byte-identical. The Japanese CID font HeiseiKakuGo-W5 is not
embedded; PDF viewers substitute their own Japanese gothic font.
Notes from the email are deliberately never printed: they may contain injected text.
"""

from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from quoteflow.models import Quote

FONT = "HeiseiKakuGo-W5"
ISSUER = ["Acme Parts株式会社（架空）", "営業部", "TEL: 00-0000-0000"]
FOOTER = "※ 本書はポートフォリオ用のサンプルです。会社・人物・価格はすべて架空です。"


def _register_font() -> None:
    if FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(FONT))


def yen(amount: Decimal) -> str:
    return f"{int(amount):,}円"


def _style(size: float, **kwargs: object) -> ParagraphStyle:
    return ParagraphStyle(f"s{size}", fontName=FONT, fontSize=size, leading=size * 1.4, **kwargs)


def _p(text: str, size: float = 9, **kwargs: object) -> Paragraph:
    # Escape everything that came from the request (company names, product names).
    return Paragraph(escape(text), _style(size, **kwargs))


def _header(quote: Quote) -> Table:
    # Business convention: "御中" for a company, "様" for a named person - never both.
    if quote.contact_name:
        to_lines = [_p(quote.company_name, 12), _p(f"{quote.contact_name} 様", 12)]
    else:
        to_lines = [_p(f"{quote.company_name} 御中", 12)]
    meta = [
        _p(f"見積番号: {quote.quote_number}"),
        _p(f"発行日: {quote.issue_date:%Y年%m月%d日}"),
        _p(f"有効期限: {quote.valid_until:%Y年%m月%d日}"),
        Spacer(1, 3 * mm),
        *[_p(line) for line in ISSUER],
    ]
    table = Table([[to_lines, meta]], colWidths=[105 * mm, 65 * mm])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return table


def _lines_table(quote: Quote) -> Table:
    rows: list[list[object]] = [["No", "品番", "品名", "数量", "単位", "単価", "金額"]]
    for i, line in enumerate(quote.lines, start=1):
        rows.append(
            [
                str(i),
                _p(line.product_code, 8),
                _p(line.name, 8),
                f"{line.quantity:,}",
                line.unit,
                yen(line.unit_price),
                yen(line.gross),
            ]
        )
    widths = [10 * mm, 34 * mm, 58 * mm, 16 * mm, 12 * mm, 20 * mm, 22 * mm]
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), FONT, 8),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF4")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9AA5B1")),
                ("ALIGN", (3, 1), (3, -1), "RIGHT"),
                ("ALIGN", (5, 1), (6, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return table


def _summary_table(quote: Quote) -> Table:
    rows = [
        ["小計", yen(quote.subtotal)],
        ["数量割引", f"-{yen(quote.discount_total)}" if quote.discount_total else yen(Decimal(0))],
        ["特急料金", yen(quote.express_fee)],
        [f"消費税（{quote.tax_rate * 100:.0f}%）", yen(quote.tax)],
        ["合計", yen(quote.total)],
    ]
    table = Table(rows, colWidths=[35 * mm, 35 * mm], hAlign="RIGHT")
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), FONT, 9),
                ("FONT", (0, -1), (-1, -1), FONT, 11),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black),
            ]
        )
    )
    return table


def render_quote_pdf(quote: Quote, path: Path) -> Path:
    """Write the quote PDF to `path` and return it."""
    _register_font()
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        invariant=1,
        title=f"御見積書 {quote.quote_number}",
        author="Acme Parts (fictional)",
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    delivery = quote.requested_delivery_date
    conditions = [
        f"ご希望納期: {delivery:%Y年%m月%d日}" if delivery else "ご希望納期: 指定なし",
        f"特急対応: {'あり' if quote.express else 'なし'}",
    ]
    story = [
        _p("御見積書", 18, alignment=1),
        Spacer(1, 6 * mm),
        _header(quote),
        Spacer(1, 6 * mm),
        _p("下記の通りお見積り申し上げます。"),
        _p(f"お見積金額（税込）: {yen(quote.total)}", 14),
        Spacer(1, 4 * mm),
        _lines_table(quote),
        Spacer(1, 4 * mm),
        _summary_table(quote),
        Spacer(1, 6 * mm),
        *[_p(line) for line in conditions],
        Spacer(1, 10 * mm),
        _p(FOOTER, 7, textColor=colors.grey),
    ]
    doc.build(story)
    return path
