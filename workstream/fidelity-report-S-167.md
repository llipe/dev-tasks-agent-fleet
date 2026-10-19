# Fidelity Report — S-167 (#311) delivery retention prune (verifier, Audit Mode)

**Verdict: High fidelity.** All 3 acceptance criteria met. Highest drift impact: **Minor**.

## AC → evidence

| AC | Evidence | Result |
| --- | --- | --- |
| `webhook.prune_deliveries()` (`security definer`, pinned `search_path`) deletes rows older than `delivery_retention_days` (default 30) in capped batches | `webhook-prune.test.ts`: 0/29-day rows kept, 31/400-day deleted; `prune_deliveries(3)` deletes exactly 3, oldest first, then the remaining 2; a config change to 7 days takes effect | Pass |
| Daily `pg_cron` job, do-block-unschedule + top-level-select style | `cron.job` row `webhook-prune-deliveries`, `17 3 * * *`, active. A temporary every-minute job running the same command reported `succeeded \| 1 row`, which proves the real cron role can execute the service-role-only function | Pass |
| A pruned `fired` delivery leaves its run intact | "never deletes the run behind a pruned fired delivery (I-8)" | Pass |

Also covered: EC-17 (a fresh row survives even a 1-day horizon), EC-35 (batch cap), I-8, a non-positive batch rejected, and service-role-only `EXECUTE`.

## Drift

| # | Finding | Type | Impact |
| --- | --- | --- | --- |
| 1 | The function returns the deleted count and rejects `p_batch < 1`. Neither is in the story. Both make the job observable in `cron.job_run_details` and prevent a no-op misconfiguration. | Intended | Minor |
| 2 | Capacity is 5000 rows a day. A sustained flood above that (R-3) would grow the table. This is documented in the migration and in the runbook's "Retention tuning" section, with the manual remedy. | Intended (documented limit) | Minor |
| 3 | `make validate-py` audit still fails on #355 (pre-existing). | Out of scope | — |

## Gates

- L2.5 `webhook-prune.test.ts`: 8/8. It was red before the migration (7 failing). The one test passing then, batch rejection, passed only because the function didn't exist yet.
- Full integration project: 221/221 (33 files).
- `make validate-js`: pass (1621 tests).
- `make validate-py`: audit fails on #355.
