.PHONY: install lint format typecheck test check data eval demo

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

# Implemented in Phase 4 (recorded-response mode, no API key needed).
demo:
	@echo "demo: not implemented yet (Phase 4)"
