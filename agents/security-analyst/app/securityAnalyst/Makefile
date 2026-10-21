# Quality toolchain for the security-analyst agent (Python package).
# Canonical targets mirror the TESTING.md command contract. Run from this dir:
#   make install   # install package + dev deps
#   make validate  # aggregate gate: lint + format-check + typecheck + test-cov + audit

.PHONY: install lint lint-fix format format-check typecheck test test-unit test-component test-cov audit audit-exception-check validate

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

# TEMPORARY audit exception (#355, removal tracked in #360) - CVE-2026-59951 / GHSA-84m7-p3x7-pcfv in mcp 1.29.0.
# semgrep (all releases through 1.181.0) pins mcp==1.29.0 exactly, so the fix (1.30.0)
# can't be installed. The vulnerable code is the MCP StreamableHTTP server transport;
# this agent runs semgrep only as a CLI subprocess and never starts an MCP server.
# Hard expiry: after 20261026 (UTC) the gate fails until the exception is removed or renewed.
# Fail-closed: a missing/malformed expiry or date also fails the gate.
# Tests: tests/component/test_audit_exception.py (delete with this block).
AUDIT_EXCEPTION_EXPIRES := 20261026
# Overridable for tests only; CI must call bare `make audit`.
AUDIT_TODAY ?= $(shell date -u +%Y%m%d)

audit-exception-check:
	@echo "$(AUDIT_EXCEPTION_EXPIRES)" | grep -Eq '^[0-9]{8}$$' || { echo "audit: invalid AUDIT_EXCEPTION_EXPIRES='$(AUDIT_EXCEPTION_EXPIRES)' (expected YYYYMMDD) - see #360"; exit 1; }
	@echo "$(AUDIT_TODAY)" | grep -Eq '^[0-9]{8}$$' || { echo "audit: could not determine UTC date (AUDIT_TODAY='$(AUDIT_TODAY)') - see #360"; exit 1; }
	@if [ "$(AUDIT_TODAY)" -gt "$(AUDIT_EXCEPTION_EXPIRES)" ]; then echo "audit: exception for CVE-2026-59951 expired on $(AUDIT_EXCEPTION_EXPIRES) - see #360"; exit 1; fi

audit: audit-exception-check
	pip-audit . --strict --ignore-vuln CVE-2026-59951

# Aggregate quality gate. Mirrors the JS/TS `validate` script contract.
# Ordered fail-fast: static checks first, then tests, then dependency audit.
validate: lint format-check typecheck test-cov audit
	@echo "validate: all gates passed"
