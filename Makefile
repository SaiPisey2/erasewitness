.PHONY: test lint typecheck fmt verify-attribution check smoke-live smoke-mem0

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

smoke-live:
	@test -n "$$TYPESAFE_API_KEY" || (echo "export TYPESAFE_API_KEY first"; exit 3)
	@test -n "$$OPENAI_API_KEY" || (echo "export OPENAI_API_KEY first"; exit 3)
	.venv/bin/erasewitness run --target reference-leaky --scenario salary --judges jev,openai --budget 0.05 --out /tmp/ew-live/runs --key /tmp/ew-live/k.key

smoke-mem0:
	@test -n "$$TYPESAFE_API_KEY" || (echo "export TYPESAFE_API_KEY first"; exit 3)
	@test -n "$$OPENAI_API_KEY" || (echo "export OPENAI_API_KEY first"; exit 3)
	.venv/bin/erasewitness run --target mem0 --scenario salary --judges jev,openai --budget 0.25 --out /tmp/ew-mem0/runs --key /tmp/ew-mem0/k.key
