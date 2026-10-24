# Runbooks

Operational procedures for this repository. One file per procedure, each
carrying preconditions, steps, verification, rollback, and escalation.

A runbook describes a procedure that is current. When the script or workflow
it documents is retired, the runbook is retired with it rather than kept as
history.

Copy `runbook-template.md` to start a new one, and add a row here.

| Runbook | Trigger | Owner | Last verified |
| ------- | ------- | ----- | ------------- |
| [bug-fix-agent](bug-fix-agent.md) | Deploying or redeploying the bug-fix runtime, running its sandbox probe, rotating its Anthropic key or Projects token, or checking its permissions | operator | 2026-10-24 (S-181) |
| [webhook-deployment](webhook-deployment.md) | Enabling webhook triggers live, adding a GitHub endpoint, or rotating its secret | operator | never (local stack only, S-166) |
