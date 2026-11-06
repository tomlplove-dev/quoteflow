"""Command-line entry point. Subcommands (run, eval, serve-mcp) are added in later phases."""

import typer

from quoteflow import __version__

app = typer.Typer(
    help="QuoteFlow: turn quote-request emails into quote PDFs.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """QuoteFlow command group (keeps subcommands working while there is only one)."""


@app.command()
def version() -> None:
    """Print the installed QuoteFlow version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
