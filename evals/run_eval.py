"""Run the extraction evaluation. Same as `quoteflow eval`; kept here so the evaluation
has an obvious entry point next to its recorded responses.

    uv run python evals/run_eval.py --model claude-opus-5-5 --model claude-haiku-5-5
    uv run python evals/run_eval.py --live --update-docs ...   # calls the API, costs money

The scoring itself lives in src/quoteflow/evaluation.py so it is type-checked and tested.
"""

import sys

from quoteflow.cli import app

if __name__ == "__main__":
    app(["eval", *sys.argv[1:]])
