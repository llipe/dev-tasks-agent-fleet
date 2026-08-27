# Quality toolchain for the dependency-update agent (Python package).
# Canonical targets mirror the TESTING.md command contract. Run from this dir:
#   make install   # install package + dev deps
#   make validate  # aggregate gate: lint + format-check + typecheck + test-cov + audit

.PHONY: install lint lint-fix format format-check typecheck test test-unit test-component test-cov audit validate

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
	pytest

test-unit:
	pytest -m unit

test-component:
	pytest -m component

test-cov:
	pytest --cov --cov-report=term-missing

audit:
	pip-audit . --strict

# Aggregate quality gate. Mirrors the JS/TS `validate` script contract.
# Ordered fail-fast: static checks first, then tests, then dependency audit.
validate: lint format-check typecheck test-cov audit
	@echo "validate: all gates passed"
