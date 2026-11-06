"""Command-line entry point. `run`, `eval` and `serve-mcp` are added in later phases."""

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from quoteflow import __version__
from quoteflow.catalog import Catalog
from quoteflow.config import Settings, load_pricing_rules
from quoteflow.models import QuoteRequest
from quoteflow.pricing import PricingError, calculate_quote
from quoteflow.render_pdf import render_quote_pdf
from quoteflow.validate import validate_request

app = typer.Typer(
    help="QuoteFlow: turn quote-request emails into quote PDFs.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """QuoteFlow command group."""


@app.command()
def version() -> None:
    """Print the installed QuoteFlow version."""
    typer.echo(__version__)


@app.command("from-json")
def from_json(
    request_json: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    out: Annotated[Path, typer.Option(help="Output directory")] = Path("out"),
    issue_date: Annotated[str | None, typer.Option(help="YYYY-MM-DD (default: today)")] = None,
    quote_number: Annotated[str | None, typer.Option(help="Default: derived from content")] = None,
) -> None:
    """Price an already-extracted QuoteRequest JSON and write the PDF. Uses no AI."""
    settings = Settings.from_env()
    catalog = Catalog.load(settings.price_list_path)
    rules = load_pricing_rules(settings.pricing_rules_path)
    request = QuoteRequest.model_validate_json(request_json.read_text(encoding="utf-8"))
    issued = date.fromisoformat(issue_date) if issue_date else date.today()

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
