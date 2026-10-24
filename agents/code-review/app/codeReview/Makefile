# Quality toolchain for the code-review agent (Python package).
# Canonical targets mirror the TESTING.md command contract and the
# security-analyst sibling. Run from this dir:
#   make install   # install package + dev deps
#   make validate  # aggregate gate: lint + format-check + typecheck + test-cov + audit

.PHONY: install lint lint-fix format format-check typecheck test test-unit test-integration test-cov audit validate

install:
	pip install -e '.[dev]'

lint:
	ruff check .

lint-fix:
	ruff check --fix .

format:
	ruff format .

format-check:
	ruff format --check .

typecheck:
	mypy .

test:
	python -m pytest

test-unit:
	python -m pytest -m unit

test-integration:
	python -m pytest -m integration || test $$? -eq 5

test-cov:
	python -m pytest --cov --cov-report=term-missing

# No audit exception: this package has no semgrep (the sibling's #360
# exception covers semgrep's mcp pin only).
audit:
	pip-audit . --strict

# Aggregate quality gate. Mirrors the JS/TS `validate` script contract.
# Ordered fail-fast: static checks first, then tests, then dependency audit.
validate: lint format-check typecheck test-cov audit
	@echo "validate: all gates passed"
