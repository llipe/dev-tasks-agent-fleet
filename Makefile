# Repo-root aggregate. Delegates to per-package toolchains.
# Two branches: the dependency-update Python agent, and the JS/TS panel package
# (run via pnpm from the workspace root). `validate` runs BOTH and fails if
# either fails.

AGENT_DIR := agents/dependency-update/app/dependencyUpdate

.PHONY: install lint format format-check typecheck test test-cov audit validate \
	install-py lint-py format-py format-check-py typecheck-py test-py test-cov-py audit-py validate-py \
	install-js lint-js format-check-js typecheck-js test-js audit-js validate-js

# ----------------------------------------------------------------------------
# Aggregate targets — run the Python branch then the JS/TS branch (fail-fast).
# ----------------------------------------------------------------------------

install: install-py install-js

lint: lint-py lint-js

format-check: format-check-py format-check-js

typecheck: typecheck-py typecheck-js

test: test-py test-js

audit: audit-py audit-js

validate: validate-py validate-js

# ----------------------------------------------------------------------------
# Python branch (dependency-update agent).
# ----------------------------------------------------------------------------

install-py:
	$(MAKE) -C $(AGENT_DIR) install

lint-py:
	$(MAKE) -C $(AGENT_DIR) lint

format-py:
	$(MAKE) -C $(AGENT_DIR) format

format-check-py:
	$(MAKE) -C $(AGENT_DIR) format-check

typecheck-py:
	$(MAKE) -C $(AGENT_DIR) typecheck

test-py:
	$(MAKE) -C $(AGENT_DIR) test

test-cov-py:
	$(MAKE) -C $(AGENT_DIR) test-cov

audit-py:
	$(MAKE) -C $(AGENT_DIR) audit

validate-py:
	$(MAKE) -C $(AGENT_DIR) validate

# ----------------------------------------------------------------------------
# JS/TS branch (panel package, via pnpm workspace filter).
# ----------------------------------------------------------------------------

install-js:
	pnpm install --frozen-lockfile

lint-js:
	pnpm --filter panel run lint

format-check-js:
	pnpm --filter panel run format:check

typecheck-js:
	pnpm --filter panel run typecheck

test-js:
	pnpm --filter panel run test

audit-js:
	pnpm --filter panel run audit

validate-js:
	pnpm --filter panel run validate
