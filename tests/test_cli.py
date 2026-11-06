from pathlib import Path

from typer.testing import CliRunner

from conftest import ROOT
from quoteflow import __version__
from quoteflow.cli import app

SAMPLES = ROOT / "data" / "samples"
runner = CliRunner()


def test_version_command_prints_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_from_json_writes_pdf_without_ai(tmp_path: Path) -> None:
    args = ["from-json", str(SAMPLES / "request_01.expected.json"), "--out", str(tmp_path)]
    result = runner.invoke(app, [*args, "--issue-date", "2026-11-09", "--quote-number", "Q-1"])
    assert result.exit_code == 0, result.output
    assert "19,437円" in result.stdout
    assert (tmp_path / "Q-1.pdf").exists()


def test_from_json_defaults_to_today_and_derived_number(tmp_path: Path) -> None:
    args = ["from-json", str(SAMPLES / "request_03.expected.json"), "--out", str(tmp_path)]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert len(list(tmp_path.glob("Q-*.pdf"))) == 1


def test_from_json_refuses_non_quote(tmp_path: Path) -> None:
    args = [
        "from-json",
        str(SAMPLES / "request_05_not_quote.expected.json"),
        "--out",
        str(tmp_path),
    ]
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert "見積依頼ではありません" in result.output
    assert not list(tmp_path.glob("*.pdf"))
