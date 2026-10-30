# Quality toolchain for the bug-fix agent (Python package).
# Canonical targets mirror the TESTING.md command contract. Run from this dir:
#   make install      # install package + dev deps
#   make validate     # aggregate gate: lint + format-check + typecheck + test-cov + audit
#   make image        # build the ARM64 image locally (needs Docker)
#   make image-smoke  # build, then run scripts/image-smoke.sh against it

IMAGE ?= bug-fix:local

.PHONY: install lint lint-fix format format-check typecheck test test-unit test-component \
	test-cov audit validate image image-smoke

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

test-component:
	python -m pytest -m component || test $$? -eq 5

test-cov:
	python -m pytest --cov --cov-report=term-missing

audit:
	pip-audit . --strict

# Aggregate quality gate. Ordered fail-fast: static checks, tests, then audit.
# The image targets are not part of it: they need Docker and run separately.
validate: lint format-check typecheck test-cov audit
	@echo "validate: all gates passed"

image:
	docker build --platform linux/arm64 -t $(IMAGE) .

image-smoke: image
	./scripts/image-smoke.sh $(IMAGE)
