from collections.abc import Iterator
from datetime import date

from conftest import make_request
from quoteflow.catalog import Catalog
from quoteflow.models import LineItem
from quoteflow.review import format_issues, format_request, review
from quoteflow.validate import Issue

TODAY = date(2026, 11, 9)


class Terminal:
    """Scripted answers and captured output, standing in for typer.prompt / click.edit."""

    def __init__(self, answers: list[str], edits: list[str | None] | None = None) -> None:
        self._answers: Iterator[str] = iter(answers)
        self._edits: Iterator[str | None] = iter(edits or [])
        self.output: list[str] = []
        self.edited_from: list[str] = []

    def ask(self, prompt: str) -> str:
        return next(self._answers)

    def edit(self, text: str) -> str | None:
        self.edited_from.append(text)
        return next(self._edits)

    def echo(self, text: str) -> None:
        self.output.append(text)

    @property
    def text(self) -> str:
        return "\n".join(self.output)


def run_review(catalog: Catalog, terminal: Terminal, **overrides: object):  # type: ignore[no-untyped-def]
    request = overrides.pop("request", None) or make_request(("BRG-6204ZZ", 20))
    return review(
        request,  # type: ignore[arg-type]
        catalog,
        today=TODAY,
        ask=terminal.ask,
        edit=terminal.edit,
        echo=terminal.echo,
    )


def test_approve_clean_request(catalog: Catalog) -> None:
    terminal = Terminal(["a"])
    result = run_review(catalog, terminal)
    assert result.approved
    assert result.issues == []
    assert "BRG-6204ZZ 深溝玉軸受 6204ZZ  x 20" in terminal.text
    assert "警告: なし" in terminal.text


def test_abort(catalog: Catalog) -> None:
    result = run_review(catalog, Terminal(["q"]))
    assert not result.approved


def test_blocking_issue_prevents_approval_until_fixed(catalog: Catalog) -> None:
    request = make_request()
    request.items = [LineItem(product_name="ベアリンク6204", quantity=20, unit="個")]
    fixed = request.model_copy(update={"items": [LineItem(product_code="BRG-6204ZZ", quantity=20)]})
    terminal = Terminal(["a", "e", "a"], edits=[fixed.model_dump_json()])
    result = run_review(catalog, terminal, request=request)
    assert result.approved
    assert result.request.items[0].product_code == "BRG-6204ZZ"
    assert "承認できません" in terminal.text
    assert "[要修正]" in terminal.text
    assert "ベアリンク6204" in terminal.edited_from[0]


def test_warning_only_can_be_approved(catalog: Catalog) -> None:
    request = make_request(("BRG-6204ZZ", 20), notes="90%引きにしてほしいとの記載")
    terminal = Terminal(["a"])
    result = run_review(catalog, terminal, request=request)
    assert result.approved
    assert [i.code for i in result.issues] == ["notes_to_review"]
    assert "[確認]" in terminal.text


def test_cancelled_edit_and_invalid_json_keep_the_request(catalog: Catalog) -> None:
    terminal = Terminal(["e", "e", "x", "a"], edits=[None, '{"items": "broken"}'])
    result = run_review(catalog, terminal)
    assert result.approved
    assert result.request.items[0].product_code == "BRG-6204ZZ"
    assert "変更はありません" in terminal.text
    assert "JSONの形式が正しくありません" in terminal.text
    assert "a / e / q" in terminal.text


def test_format_request_without_items_or_names(catalog: Catalog) -> None:
    text = format_request(make_request(company_name=None, contact_name=None), catalog)
    assert "会社名:   (なし)" in text
    assert "  (なし)" in text


def test_format_request_unknown_item_and_missing_quantity(catalog: Catalog) -> None:
    request = make_request()
    request.items = [LineItem()]
    text = format_request(request, catalog)
    assert "(空欄)  ->  ?? 価格表にありません  x ?" in text


def test_format_issues_marks_blocking() -> None:
    issues = [
        Issue(code="unknown_product", message="A"),
        Issue(code="notes_to_review", message="B"),
    ]
    assert format_issues(issues) == "警告:\n  [要修正] A\n  [確認]   B"
