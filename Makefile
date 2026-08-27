# Repo-root aggregate. Delegates to per-package toolchains.
# The active package is the dependency-update Python agent.

AGENT_DIR := agents/dependency-update/app/dependencyUpdate

.PHONY: install lint format format-check typecheck test test-cov audit validate

install:
	$(MAKE) -C $(AGENT_DIR) install

lint:
	$(MAKE) -C $(AGENT_DIR) lint

format:
	$(MAKE) -C $(AGENT_DIR) format

format-check:
	$(MAKE) -C $(AGENT_DIR) format-check

typecheck:
	$(MAKE) -C $(AGENT_DIR) typecheck

test:
	$(MAKE) -C $(AGENT_DIR) test

test-cov:
	$(MAKE) -C $(AGENT_DIR) test-cov

audit:
	$(MAKE) -C $(AGENT_DIR) audit

validate:
	$(MAKE) -C $(AGENT_DIR) validate
