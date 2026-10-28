# Runbooks

Operational procedures for this repository. One file per procedure, each
carrying preconditions, steps, verification, rollback, and escalation.

A runbook describes a procedure that is current. When the script or workflow
it documents is retired, the runbook is retired with it rather than kept as
history.

Copy `runbook-template.md` to start a new one, and add a row here.

| Runbook | Trigger | Owner | Last verified |
| ------- | ------- | ----- | ------------- |
| [bug-fix-agent](bug-fix-agent.md) | Deploying or redeploying the bug-fix runtime, running its sandbox probe, applying or rolling back its `agents` seed row, rotating its Anthropic key or Projects token, checking its permissions, or verifying a Wave A run | operator | 2026-10-25 (S-181 deploy, S-182 probe, S-184 seed row, Wave A verified live on runtime v7) |
| [webhook-deployment](webhook-deployment.md) | Enabling webhook triggers live, adding a GitHub endpoint, or rotating its secret | operator | never (local stack only, S-166) |
| [ci-quality-gates](ci-quality-gates.md) | CI red, or CI missing, on a PR or push to `main` or `integration/**` | operator | never (trigger change, first run on its own PR) |
