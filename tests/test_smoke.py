"""Phase 1 smoke test: the package imports and the CLI starts without an API key."""

from typer.testing import CliRunner

from quoteflow import __version__
from quoteflow.cli import app


def test_version_command_prints_version() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__
