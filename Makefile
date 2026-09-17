# Repo-root aggregate. Delegates to per-package toolchains.
# Two branches: the Python agents (every directory in AGENT_DIRS, in order),
# and the JS/TS panel package (run via pnpm from the workspace root).
# `validate` runs ALL of them and fails if any fails.

AGENT_DIRS := agents/dependency-update/app/dependencyUpdate \
	agents/security-analyst/app/securityAnalyst

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
# Python branch (one sub-make per agent in AGENT_DIRS, fail-fast).
# ----------------------------------------------------------------------------

install-py:
	@for d in $(AGENT_DIRS); do $(MAKE) -C $$d install || exit 1; done

lint-py:
	@for d in $(AGENT_DIRS); do $(MAKE) -C $$d lint || exit 1; done

format-py:
	@for d in $(AGENT_DIRS); do $(MAKE) -C $$d format || exit 1; done

format-check-py:
	@for d in $(AGENT_DIRS); do $(MAKE) -C $$d format-check || exit 1; done

typecheck-py:
	@for d in $(AGENT_DIRS); do $(MAKE) -C $$d typecheck || exit 1; done

test-py:
	@for d in $(AGENT_DIRS); do $(MAKE) -C $$d test || exit 1; done

test-cov-py:
	@for d in $(AGENT_DIRS); do $(MAKE) -C $$d test-cov || exit 1; done

audit-py:
	@for d in $(AGENT_DIRS); do $(MAKE) -C $$d audit || exit 1; done

validate-py:
	@for d in $(AGENT_DIRS); do $(MAKE) -C $$d validate || exit 1; done

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
