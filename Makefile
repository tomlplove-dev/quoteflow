.PHONY: install lint format typecheck test check data demo-fixtures demo record eval

install:
	uv sync

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

typecheck:
	uv run mypy src

test:
	uv run pytest --cov --cov-report=term-missing

# Same steps as CI.
check: lint typecheck test

# Regenerate all synthetic data from the fixed seed.
data:
	uv run python scripts/make_synthetic_data.py

# Implemented in Phase 5.
eval:
	@echo "eval: not implemented yet (Phase 5)"

# Demo dates are fixed so the replayed requests match the saved responses.
DEMO_FLAGS = --replay evals/fixtures/demo --received-date 2026-11-09 --issue-date 2026-11-09 --out out/demo
RECORD_FLAGS = --record evals/fixtures/demo --received-date 2026-11-09 --issue-date 2026-11-09 --out out/demo

# Rebuild the stand-in responses used by the demo (no API key needed).
demo-fixtures:
	uv run python scripts/make_demo_fixtures.py

# End-to-end run without an API key, using saved responses. The last two runs are
# expected to stop: one contains a prompt injection, one is not a quote request.
demo:
	uv run quoteflow run data/samples/request_01.txt --yes $(DEMO_FLAGS)
	uv run quoteflow run data/samples/request_03.eml --yes $(DEMO_FLAGS)
	-uv run quoteflow run data/samples/request_04_injection.txt --yes $(DEMO_FLAGS)
	-uv run quoteflow run data/samples/request_05_not_quote.txt --yes $(DEMO_FLAGS)

# Replace the stand-ins with real Claude responses (needs ANTHROPIC_API_KEY, costs money).
record:
	-uv run quoteflow run data/samples/request_01.txt --yes $(RECORD_FLAGS)
	-uv run quoteflow run data/samples/request_03.eml --yes $(RECORD_FLAGS)
	-uv run quoteflow run data/samples/request_04_injection.txt --yes $(RECORD_FLAGS)
	-uv run quoteflow run data/samples/request_05_not_quote.txt --yes $(RECORD_FLAGS)
