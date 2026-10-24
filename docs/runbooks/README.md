# Runbooks

Operational procedures for this repository. One file per procedure, each
carrying preconditions, steps, verification, rollback, and escalation.

A runbook describes a procedure that is current. When the script or workflow
it documents is retired, the runbook is retired with it rather than kept as
history.

Copy `runbook-template.md` to start a new one, and add a row here.

| Runbook                                     | Trigger                                                                          | Owner    | Last verified                                   |
| ------------------------------------------- | -------------------------------------------------------------------------------- | -------- | ----------------------------------------------- |
| [webhook-deployment](webhook-deployment.md) | Enabling webhook triggers live, adding a GitHub endpoint, or rotating its secret | operator | never (local stack only, S-166)                 |
| [ci-quality-gates](ci-quality-gates.md)     | CI red, or CI missing, on a PR or push to `main` or `integration/**`             | operator | never (trigger change, first run on its own PR) |
