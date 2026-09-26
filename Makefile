.PHONY: test lint typecheck fmt verify-attribution check

test:
	.venv/bin/pytest -q

lint:
	.venv/bin/ruff check src tests
	.venv/bin/ruff format --check src tests

typecheck:
	.venv/bin/mypy src

fmt:
	.venv/bin/ruff format src tests
	.venv/bin/ruff check --fix src tests

verify-attribution:
	scripts/verify-attribution.sh

check: lint typecheck test verify-attribution
