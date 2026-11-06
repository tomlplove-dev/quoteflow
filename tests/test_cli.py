from pathlib import Path

import anthropic
import pytest
from typer.testing import CliRunner

from conftest import ROOT
from quoteflow import __version__
from quoteflow.cli import app
from quoteflow.extract import replay_sender

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


FIXTURES = ROOT / "evals" / "fixtures" / "demo"
DEMO = ["--replay", str(FIXTURES), "--received-date", "2026-11-09", "--issue-date", "2026-11-09"]


def test_run_with_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUOTEFLOW_LOG_DIR", str(tmp_path / "logs"))
    args = ["run", str(SAMPLES / "request_01.txt"), "--yes", "--out", str(tmp_path), *DEMO]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert "19,437円" in result.stdout


def test_run_yes_refuses_when_warnings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUOTEFLOW_LOG_DIR", str(tmp_path / "logs"))
    args = [
        "run",
        str(SAMPLES / "request_04_injection.txt"),
        "--yes",
        "--out",
        str(tmp_path),
        *DEMO,
    ]
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert "90%引き" in result.output
    assert "自動承認（--yes）はできません" in result.output


def test_run_interactive_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUOTEFLOW_LOG_DIR", str(tmp_path / "logs"))
    args = [
        "run",
        str(SAMPLES / "request_02.xlsx"),
        "--out",
        str(tmp_path),
        "--issue-date",
        "2026-11-09",
    ]
    result = runner.invoke(app, args, input="a\n")
    assert result.exit_code == 0, result.output
    assert "[a] 承認 / [e] 修正 / [q] 中止" in result.output
    assert "25,844円" in result.output


def test_run_rejects_replay_and_record_together(tmp_path: Path) -> None:
    args = [
        "run",
        str(SAMPLES / "request_01.txt"),
        "--replay",
        str(tmp_path),
        "--record",
        str(tmp_path),
    ]
    result = runner.invoke(app, args)
    assert result.exit_code != 0


def test_run_live_without_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_client(settings: object) -> object:
        raise anthropic.AnthropicError("no API key")

    monkeypatch.setattr("quoteflow.cli.live_sender", no_client)
    args = ["run", str(SAMPLES / "request_01.txt"), "--out", str(tmp_path)]
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert "APIキー" in result.output


def test_run_record_wraps_live_sender(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUOTEFLOW_LOG_DIR", str(tmp_path / "logs"))
    replayed = replay_sender(FIXTURES)
    monkeypatch.setattr("quoteflow.cli.live_sender", lambda settings: replayed)
    record_dir = tmp_path / "recorded"
    args = ["run", str(SAMPLES / "request_01.txt"), "--yes", "--out", str(tmp_path)]
    args += [
        "--record",
        str(record_dir),
        "--received-date",
        "2026-11-09",
        "--issue-date",
        "2026-11-09",
    ]
    args += ["--model", "claude-opus-5-5"]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert len(list(record_dir.glob("*.json"))) == 1
