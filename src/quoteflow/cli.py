"""Command-line entry point. `eval` and `serve-mcp` are added in later phases."""

from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Annotated

import anthropic
import click  # typer is built on click; click.edit opens $EDITOR for the review step
import typer

from quoteflow import __version__
from quoteflow.catalog import Catalog
from quoteflow.config import Settings, load_dotenv, load_pricing_rules
from quoteflow.extract import Send, live_sender, recording_sender, replay_sender
from quoteflow.models import QuoteRequest
from quoteflow.pipeline import Reviewer, run_pipeline
from quoteflow.pricing import PricingError, calculate_quote
from quoteflow.render_pdf import render_quote_pdf
from quoteflow.review import ReviewResult, review
from quoteflow.validate import validate_request

app = typer.Typer(
    help="QuoteFlow: turn quote-request emails into quote PDFs.",
    no_args_is_help=True,
)

DateOption = Annotated[str | None, typer.Option(help="YYYY-MM-DD (default: today)")]


def _parse_date(value: str | None) -> date:
    return date.fromisoformat(value) if value else date.today()


def _terminal_reviewer(catalog: Catalog, today: date) -> Reviewer:
    def reviewer(request: QuoteRequest) -> ReviewResult:
        return review(
            request, catalog, today=today, ask=typer.prompt, edit=click.edit, echo=typer.echo
        )

    return reviewer


@app.callback()
def main() -> None:
    """QuoteFlow command group."""
    load_dotenv(Path(".env"))


@app.command()
def version() -> None:
    """Print the installed QuoteFlow version."""
    typer.echo(__version__)


@app.command()
def run(
    path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help=".txt / .eml / .xlsx")],
    out: Annotated[Path, typer.Option(help="Output directory")] = Path("out"),
    yes: Annotated[
        bool, typer.Option("--yes", help="Approve automatically (only with zero warnings)")
    ] = False,
    issue_date: DateOption = None,
    received_date: Annotated[
        str | None,
        typer.Option(help="When the email arrived (default: Date header, else issue date)"),
    ] = None,
    model: Annotated[str | None, typer.Option(help="Override QUOTEFLOW_MODEL")] = None,
    replay: Annotated[
        Path | None,
        typer.Option(help="Use recorded responses from this directory (no API key needed)"),
    ] = None,
    record: Annotated[
        Path | None, typer.Option(help="Save live responses to this directory")
    ] = None,
) -> None:
    """Read a request, extract it, let a person review it, then price it and write the PDF."""
    settings = Settings.from_env()
    if model:
        settings = replace(settings, model=model)
    if replay and record:
        raise typer.BadParameter("use either --replay or --record, not both")
    catalog = Catalog.load(settings.price_list_path)
    rules = load_pricing_rules(settings.pricing_rules_path)
    issued = _parse_date(issue_date)

    send: Send | None = None
    if path.suffix.lower() != ".xlsx":
        if replay:
            send = replay_sender(replay)
        else:
            try:
                send = live_sender(settings)
            except anthropic.AnthropicError as e:
                typer.echo(
                    f"Claude APIに接続できません（APIキーを .env に設定してください）: {e}",
                    err=True,
                )
                raise typer.Exit(code=1) from e
            if record:
                send = recording_sender(send, record)

    reviewer = None if yes else _terminal_reviewer(catalog, issued)
    result = run_pipeline(
        path,
        settings=settings,
        catalog=catalog,
        rules=rules,
        send=send,
        reviewer=reviewer,
        out_dir=out,
        issue_date=issued,
        received_at=date.fromisoformat(received_date) if received_date else None,
    )
    if result.issues and yes:
        for issue in result.issues:
            typer.echo(f"[警告] {issue.message}", err=True)
    typer.echo(result.message)
    if result.status in {"failed", "needs_review"}:
        raise typer.Exit(code=1)


@app.command("from-json")
def from_json(
    request_json: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    out: Annotated[Path, typer.Option(help="Output directory")] = Path("out"),
    issue_date: DateOption = None,
    quote_number: Annotated[str | None, typer.Option(help="Default: derived from content")] = None,
) -> None:
    """Price an already-extracted QuoteRequest JSON and write the PDF. Uses no AI."""
    settings = Settings.from_env()
    catalog = Catalog.load(settings.price_list_path)
    rules = load_pricing_rules(settings.pricing_rules_path)
    request = QuoteRequest.model_validate_json(request_json.read_text(encoding="utf-8"))
    issued = _parse_date(issue_date)

    for issue in validate_request(request, catalog, today=issued):
        typer.echo(f"[警告] {issue.message}", err=True)
    try:
        quote = calculate_quote(
            request, catalog, rules, issue_date=issued, quote_number=quote_number
        )
    except PricingError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e

    pdf = render_quote_pdf(quote, out / f"{quote.quote_number}.pdf")
    typer.echo(f"合計 {int(quote.total):,}円 -> {pdf}")


if __name__ == "__main__":
    app()
