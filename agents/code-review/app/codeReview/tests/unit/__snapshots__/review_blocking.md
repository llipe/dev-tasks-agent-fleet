<!-- code-review-agent:v1 run=0b7c4e9a-1d2f-4a3b-8c5d-6e7f8091a2b3 sha=9f2c4e1a7b3d5f60812a4c6e8b0d2f4a6c8e0b1d -->

## Code review: **blocking** · `9f2c4e1`

### Blocking

**B1 · correctness · `src/app.py:120-134`** — Retry double-charges on timeout

- **Fails when:** the gateway times out after the charge is accepted, and \`retry()\` sends it again
- **Consequence:** the customer is charged twice; ping @​payments-team

**B2 · edge\_case · `src/limits.py:42`** — Zero limit &lt;b&gt;divides&lt;/b&gt; by zero

- **Fails when:** limit = 0
- **Consequence:** ZeroDivisionError crashes the worker

### Verifier

- **V1 (confirmed)** from `workstream/fidelity-report-S-170.md`: \| DR-1 \| Critical \| Unintended \| retries are not idempotent \| — Still visible in src/app.py at this head.
- **V2 (not reproduced)** from `workstream/fidelity-report-S-170.md`: \| DR-4 \| Critical \| Unintended \| no audit row on refund \| — Fixed by the new idempotency key.
- **V3 (unchecked)** from `workstream/fidelity-report-S-170.md`: \| DR-6 \| Critical \| Unintended \| webhook secret logged \| — not checked by the model
- Other drift: 3 items, see the report.

<details><summary>Suggestions (2)</summary>

**S1 · maintainability · `src/app.py:10`** — Extract the retry policy. Two call sites will drift.

**S2 · correctness · `src/old.py:5-9`** — Dead branch. Readers waste time on it. (Downgraded: not located in the diff.)

</details>

**Context:** issue #315 · spec `workstream/specification-prd-webhook-triggers.md` (trimmed) · 2 files too large to include in full: `src/app.py`, `src/old.py` · listed by name only: `pnpm-lock.yaml` (lockfile), `assets/logo.png` (no text diff) · base withheld: `src/moved.py` (previous name is excluded)

<sub>Not reviewed here: fidelity and AC coverage (`verifier`); lint, format, typecheck, tests, dependency audit, coverage (CI); SAST and secrets (CI, `security-analyst`). Model `us.openai.sol-v1:0` · rubric v1 · [run](https://dt-agent-fleet-panel.fly.dev/runs/0b7c4e9a-1d2f-4a3b-8c5d-6e7f8091a2b3)</sub>
