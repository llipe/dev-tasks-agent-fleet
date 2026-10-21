# Fidelity Report — S-174 (#319) notify-sweep for webhook runs + #302 (verifier, Audit Mode)

**Verdict: High fidelity.** All 3 acceptance criteria met. Highest drift impact: **Minor**.

## AC → evidence

| AC | Evidence | Result |
| --- | --- | --- |
| The sweep resolves the trigger from `triggered_by` for `schedule:*` and `webhook:*` and records the same kinds | L2.5 `notify-sweep.test.ts`: a webhook run gets exactly one `run_failed` over two sweeps, linked through `webhook_rule_id`, with the endpoint and rule named in the title; one `pr_opened`; `run_succeeded` only for a rule with `notify_on_success`. A malformed `webhook:` trigger doesn't break the sweep. Manual runs are never notified. The 5 original scheduled-run cases are unchanged and green | Pass |
| Notifications appear in the table, feed and digest | Feed: `webhook_rule_id` drives a "View webhooks ▸" link; schedule links only appear for schedules. Digest: an "Auto-disabled webhook rules" section, and a property test that no row of any kind is dropped (L1 `notification-view`, `ses`) | Pass |
| #302 resolved consistently | Left join (D-W17): an orphaned scheduled run gets `run_failed` with a null schedule link and no G3; an orphaned PR still gets `pr_opened`; an orphaned success stays silent; the same holds for a deleted webhook rule | Pass |

## Drift

| # | Finding | Type | Impact |
| --- | --- | --- | --- |
| 1 | **Fix for a gap S-173 left.** S-173 added the `webhook_rule_auto_disabled` kind in SQL but not to `NotificationKind`. The feed would have rendered no dot color, and the digest would have **silently dropped** those rows from the email (`KIND_ORDER` filter). Fixed here and covered by a property test. | Unintended (fixed) | Minor |
| 2 | Webhook G3 does not count runs that started and later failed (D-W18). Scheduled G3 does, through the sweep. This is consistent with S-173's AC ("fire failure"), but the two triggers differ, and it should be stated in spec §8.4. | Intended | Minor |
| 3 | **Live backfill.** On the first sweep after the push, the left join notifies existing orphaned scheduled runs. Read-only check against live: 1 failed run, 0 PRs. That's one extra notification and possibly one extra digest line. | Intended | Minor |
| 4 | Formatting: `prettier --write .` reported writing `notify-sweep.test.ts`, but `--check` still failed until a second direct `--write`. Cause unknown; the reliable sequence is write, check, and write again if needed. | Process note | — |

## Gates

- L2.5 `notify-sweep` 13/13; red first: 7 new cases failed and the 6 existing cases passed.
- Scheduler and webhook regression green (84 tests across 8 files).
- L1 `notification-view` and `ses` 18/18; red first: 4 failed.
- SQL mutants, all caught: inner join (#302) 1 failing; schedule-only sweep 2; success ignoring opt-in 1; wrong rule-id offset 3.
- `make validate-js` (1905 tests), `make validate-py` and `next build`: pass.
