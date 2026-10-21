# Fidelity Audit — Scheduler Stories S-155–S-160 (Waves C–D)

| | |
| --- | --- |
| **Mode** | Audit (grey-box, post-merge, read-only) |
| **Repository** | `llipe/dev-tasks-agent-fleet` |
| **Branch / commit** | `main` @ `e5dbbbe` (HEAD at audit time) |
| **Scope** | Issues #267 #268 #269 #270 #271 #272 — PRD `docs/requirements/prd-agent-scheduler.md`, delivered via integration PR #296 |
| **Overall fidelity** | **High** |
| **Highest drift impact present** | **Minor** |
| **Verdict policy** | Drift is non-blocking; this audit is additive and does not gate completion. |

## Header / Verdict (all six)

- **#267 S-155 (G1 overlap):** Fidelity High — all ACs MET on main. **CLOSE.**
- **#268 S-156 (G5 open-PR):** Fidelity High — all ACs MET on main. **CLOSE.**
- **#269 S-157 (G3 circuit breaker):** Fidelity High — all ACs MET on main. **CLOSE.**
- **#270 S-158 (notify-sweep):** Fidelity High — all ACs MET on main. **CLOSE.**
- **#271 S-159 (SES digest):** Fidelity Medium — code/endpoint/cron MET; the **IAM `ses:SendEmail` policy doc + runbook SES/secrets section are not in the repo** (Minor drift, live-only grant NOT VERIFIABLE-HERE). **CLOSE-WITH-FOLLOW-UP.**
- **#272 S-160 (release-gate internal-401):** Fidelity High — all ACs MET on main. **CLOSE.**

## Human-readable summary (plain language)

The scheduler's "guardrails" and "notifications" work landed on `main` and the code
backing every rule is present and tested. In plain terms:

- A schedule will **not fire again while its previous run is still going** (overlap),
  and that hold releases itself once the earlier run finishes.
- A schedule **stops firing while a pull request it opened is still unhandled**, and an
  operator can click "resume anyway" or start a manual run to clear it.
- A schedule that **fails three times in a row pauses itself and sends one alert**, and a
  single success resets the counter.
- A once-a-minute background job **records failures and opened pull requests the panel
  didn't catch live** (including runs the timeout-reaper marked), exactly once each.
- A **once-a-day email digest** is sent only when there's something to report; an empty
  day sends nothing, and a send failure safely retries the next day.
- The release safety-check now **proves the internal scheduler endpoints reject
  unauthenticated calls** (401), so a public "fire" hole can't ship unnoticed.

The one gap worth a follow-up is on the email story (#271): the email-sending **code** is
present, pinned, and tested, and production logs show the digest endpoint ran, but the
**AWS permission that lets it actually send mail** and the **operator runbook steps for the
email secrets** are not committed in this repository. They were almost certainly applied
directly to AWS/Fly (live), but that can't be verified from the code on `main` — hence a
non-blocking follow-up rather than a block.

---

## #267 — S-155: G1 overlap suppression

Implementation: `supabase/migrations/20261013164000_scheduler_g1_overlap.sql`.
Tests: `panel/tests/integration/guardrail-overlap.test.ts` (L2.5).

| AC | Verdict | Evidence |
| --- | --- | --- |
| AC-1 — non-terminal prior run blocks next firing w/ reason `overlap` (AC4) | **MET** | `has_active_run()` on `effective_status in ('queued','running')` + the in-loop block to `state='blocked', block_reason='overlap'` (g1_overlap.sql:24-34, 70-75); test "blocks a due schedule while a fresh running run… (AC4)" (overlap.test.ts:108). |
| AC-2 — block clears automatically when the run reaches terminal | **MET** | G1 auto-clear `update … set state='active'… where block_reason='overlap' and not has_active_run()` runs at the top of each tick (g1_overlap.sql:60-64); test "auto-clears and fires once the prior run is terminal (AC4)" (overlap.test.ts:119). |
| AC-3 — stale `running` does not block forever (effective_status / reaper) | **MET** | `has_active_run` reads `v_runs.effective_status`, so a stale `running` past the reaper threshold reads `timed_out` and is not active (g1_overlap.sql:24-33); test "a STALE running run … does NOT block (effective_status=timed_out)" (overlap.test.ts:140). |

Also covered (defense-in-depth, scope): the fire endpoint has the ordered re-check hook
(`fire/route.ts:` step 3 comment), and block scope is `(agent,repository)` with null-safe
equality (overlap.test.ts:148). Spec SD-G1/SD-G0/SD-G6 honored.

**Overall: CLOSE.**

---

## #268 — S-156: G5 open-PR backoff (phased a+c) + manual clear

Implementation: `supabase/migrations/20261013165000_scheduler_g5_open_pr.sql`;
`panel/lib/supabase/queries.ts::clearSchedulePrBlock` (queries.ts:~930);
`panel/app/(panel)/schedules/actions.ts` (G5-c Server Action, actions.ts:73-83).
Tests: `panel/tests/integration/guardrail-open-pr.test.ts` (L2.5).

| AC | Verdict | Evidence |
| --- | --- | --- |
| AC-1 — scheduled run that opened a PR blocks next firing w/ reason `open_pr` (AC8) | **MET** | `open_pr_block_run()` finds the most-recent unresolved `pull_request` artifact; in-loop block sets `state='blocked', block_reason='open_pr', pr_block_run_id` (g5_open_pr.sql:30-50, 96-102); test "blocks … while a prior run's PR is unresolved (AC8)" (open-pr.test.ts:132). |
| AC-2 — manual clear resumes firing | **MET** | `clearSchedulePrBlock` sets `pr_block_cleared_at=now()`; auto-clear re-evaluates `open_pr_block_run(…, pr_block_cleared_at)` → null (g5_open_pr.sql:66-69, predicate line ~45); Server Action wired (actions.ts:73-83); test "resumes firing after a manual clear (G5-c)" (open-pr.test.ts:143). |
| AC-3 — later manual run supersedes the block (G5-a) | **MET** | Supersede branch: `not exists (… runs m … trigger_type='manual' and created_at > pr_at)` (g5_open_pr.sql:~46-49); test "resumes firing when a later manual run supersedes the PR (G5-a)" (open-pr.test.ts:157). |
| AC-4 — v1 does NOT consult GitHub for PR state (documented limitation) | **MET** | Header comment documents FR-FF1 as fast-follow and `pr_block_*` columns as the future seam; resolution is purely DB-local (g5_open_pr.sql:9-18). Matches issue "Out of scope" note. |

L1 resolve predicate is exercised through the L2.5 re-block edge "stays blocked when a NEW PR
appears after a prior clear (EC-18)" (open-pr.test.ts:169). Spec SD-G5/SD-G5a/SD-N3 honored.

**Overall: CLOSE.**

---

## #269 — S-157: G3 circuit breaker (consecutive-failure auto-pause)

Implementation: `supabase/migrations/20261013166000_scheduler_g3_circuit_breaker.sql`
(`public.scheduler_record_fire_failure`); reset in
`panel/lib/supabase/queries.ts::recordScheduleFired` (queries.ts:860-878); increment hook in
`fire/route.ts` (recordScheduleFireFailure on invoke/validation failure).
Tests: `panel/tests/integration/guardrail-autopause.test.ts` (L2.5).

| AC | Verdict | Evidence |
| --- | --- | --- |
| AC-1 — 3 consecutive failures → `paused` + exactly one `schedule_auto_paused` notif + stops firing (AC6) | **MET** | Atomic increment then trip **only on `v_count = v_threshold`** (`==`, not `>=`) with the notification `insert` in the same function/txn (g3.sql:33-66); test "increments on each failure, pauses + notifies exactly once at the threshold (AC6)" (autopause.test.ts:92). Paused schedules aren't selected by the tick → stops firing. |
| AC-2 — a manual resume (S-161) clears it | **MET (seam)** | Trip condition is exact-equality so a resumed schedule re-notifies only on a fresh threshold crossing (g3.sql comment 40-44); manual-resume action is S-161's surface, out of this issue's code but the breaker is designed to cooperate. Verified by the reset test below + the `==` guard. |
| AC-3 — one subsequent success resets the counter to 0 | **MET** | `recordScheduleFired` sets `consecutive_failures: 0, state:'active', block_reason:null` (queries.ts:866-872); test "a success resets the counter (2 fail, success, 2 fail -> no pause)" (autopause.test.ts:110). |

L1 threshold decision exercised via per-schedule threshold test "respects a per-schedule
threshold of 1" (autopause.test.ts:137). Spec SD-G3/SD-N1/SD-G6 honored. The reaper-fed path
is covered under #270.

**Overall: CLOSE.**

---

## #270 — S-158: notify-sweep tick (durable recording + reaper failures)

Implementation: `supabase/migrations/20261013167000_scheduler_notify_sweep.sql`
(`scheduler.sweep_schedule_notifications()` + `cron.schedule('scheduler-notify-sweep','* * * * *',…)`).
Tests: `panel/tests/integration/notify-sweep.test.ts` (L2.5).

| AC | Verdict | Evidence |
| --- | --- | --- |
| AC-1 — reaper-marked `timed_out` run → exactly one `run_failed` + increments counter (AC10) | **MET** | Block 1 selects `effective_status in ('failed','failed_to_start','timed_out')` with `not exists` guard, inserts `on conflict (run_id,kind) do nothing`, and feeds `scheduler_record_fire_failure` gated on `row_count` (notify_sweep.sql:66-115); tests "records exactly one run_failed… and feeds G3 (AC10)" (notify-sweep.test.ts:112) + "materializes a reaper 'timed_out' failure via effective_status (AC10)" (:126). Counter path also "three terminal failures auto-pause… (G3 via the sweep)" (:146). |
| AC-2 — sweep is idempotent (re-run → no dup rows) | **MET** | Every insert is `on conflict (run_id,kind) do nothing` against `uq_notifications_run_kind` (schema.sql:126); G3 feed gated on `get diagnostics … row_count` so re-run never re-counts (notify_sweep.sql:109-115). Idempotency asserted across the test suite's re-run assertions. |
| AC-3 — `run_succeeded` only with per-schedule opt-in | **MET** | Block 3 joins `and s.notify_on_success` (notify_sweep.sql:~190; column schema.sql:63); test "records run_succeeded only when the schedule opted in" (notify-sweep.test.ts:180). |
| AC-4 — late PR artifact → one `pr_opened` + the G5 block | **MET** | Block 2 inserts `pr_opened` (distinct-on earliest artifact) and arms `state='blocked', block_reason='open_pr', pr_block_run_id` on an `active` schedule (notify_sweep.sql:120-175); test "records pr_opened for a late PR artifact and arms the G5 block (SD-N3)" (notify-sweep.test.ts:159). |

`schedule_id_of()` links runs via `triggered_by='schedule:<uuid>'` with a uuid-format guard
(notify_sweep.sql:27-45). Cron registered idempotently (unschedule-if-present then schedule).
Spec SD-N1/SD-N2/SD-N3/SD-G3 honored.

**Overall: CLOSE.**

---

## #271 — S-159: SES sender + IAM + daily digest endpoint/tick

Implementation: `panel/lib/aws/ses.ts` (render + send); `panel/app/api/internal/notifications/digest/route.ts`;
`panel/lib/supabase/queries.ts` (`getUndeliveredNotifications` :937, `markNotificationsEmailed` :954);
`supabase/migrations/20261013168000_scheduler_daily_digest.sql` (`schedule_daily_digest()` + cron).
Tests: `panel/tests/unit/ses.test.ts` (L1, 6 tests, **run & passing locally**),
`panel/tests/integration/digest-marking.test.ts` (L2.5).

| AC | Verdict | Evidence |
| --- | --- | --- |
| AC-1 — a day with notable events → exactly one email + those rows `emailed_at` (AC12) | **MET** | `getUndeliveredNotifications` (`emailed_at is null`, oldest-first) → `renderDigest` → `sendDigestEmail` → `markNotificationsEmailed` **only after** a confirmed send (digest/route.ts:POST steps 2-5; queries.ts:937-968); test "selects only undelivered rows; marking removes them from the next selection" (digest-marking.test.ts:62) + ses render tests. |
| AC-2 — empty window → 204, no email | **MET** | `if (rows.length === 0) → 204, logs empty_window, no SES call` (digest/route.ts step 3). Production log 12:58:23Z `empty_window` corroborates. |
| AC-3 — send failure leaves `emailed_at` null (retries next day) | **MET** | SES throw → `catch` returns 502 and `markNotificationsEmailed` is never reached (digest/route.ts step 5); `sendDigestEmail` throws `SesSendFailedError` with no leak (ses.ts); test "a send failure (no mark call) leaves emailed_at null -> retried next window" (digest-marking.test.ts:80) + ses.test.ts:97. |
| AC-4 — no static AWS keys (OIDC → STS) (AC15) | **PARTIAL / NOT VERIFIABLE-HERE (live)** | Code reuses `awsCredentials` from `lib/aws/credentials.ts` (Fly OIDC→STS), never static keys (ses.ts:`clientFactory`). The *code* path is MET; the *live grant* (the IAM role actually having `ses:SendEmail`/`SendRawEmail` scoped to the verified sender ARN) is a live AWS change and **not present as a committed policy doc** — see drift D1. Release-gate check 3/5 proves no static keys at runtime (live). |
| AC-5 — digest covers notable events only (no per-success rows, no all-runs roll-up) | **MET** | Selection reads the `notifications` table only (which holds notable kinds: run_failed/schedule_auto_paused/pr_opened + opt-in run_succeeded); `KIND_ORDER`/`KIND_LABEL` enumerate exactly those four kinds (ses.ts). No all-runs source is queried. |

Dependency pin: `@aws-sdk/client-ses` **exact `3.1126.0`** (panel/package.json:28), audit-clean per CI.
Cron `scheduler-daily-digest` registered via `schedule_daily_digest()` with the SD-N6a static-UTC
conversion (daily_digest.sql). Production log shows a `notification_digest` run (one `UNAUTHORIZED`
at 12:58:21Z, then `empty_window` at 12:58:23Z — see follow-up F3).

**Drift D1 (Minor, Undetermined→Unintended):** the issue scope and AC4 call for the IAM role to
gain `ses:SendEmail`/`ses:SendRawEmail` on the verified sender ARN, plus a **runbook update** and
`NOTIFICATION_SENDER`/`NOTIFICATION_RECIPIENT` secrets. Neither a committed IAM policy document under
`infra/` (only `agentcore-invoke-policy.json` + `trust-policy.json` exist; no SES statement anywhere
in `infra/`) nor a runbook SES/digest-secrets section (`docs/runbooks/panel-deployment.md` has no
`NOTIFICATION_SENDER`/SES content) is present on `main`. The AGENTS.md FR-49a rule ("deliver a runbook
in the same PR as any infra change") appears unmet for the SES grant. The grant was most likely applied
live out-of-band; that cannot be verified from `main`. **Non-blocking.**

**Overall: CLOSE-WITH-FOLLOW-UP.**

---

## #272 — S-160: release-gate assertion — /api/internal/** rejects unauthenticated

Implementation: `panel/scripts/panel-auth-check.mjs::checkInternalRejected` (CHECK 5) +
`evaluateAuthGate` wiring; `scripts/verify-panel-auth.sh` CHECK 5 probe (verify-panel-auth.sh:269-296,
`INTERNAL_PATH=/api/internal/schedules/0000…/fire`, expect 401).
Tests: `panel/tests/unit/panel-auth-check.test.ts` (L1, 47 tests, **run & passing locally**).

| AC | Verdict | Evidence |
| --- | --- | --- |
| AC-1 — gate fails release if internal endpoint returns anything but 401 to unauth/wrong-secret probe | **MET** | `checkInternalRejected` passes **only** on 401; 200/202 → "open invoke hole", 404/409 → "got past the secret check", error/other → fail-closed (panel-auth-check.mjs CHECK 5); wired into `evaluateAuthGate.internalRejected`. Live wrapper probes the nonexistent-schedule fire path (verify-panel-auth.sh:277). Production: release-gate check 5 (internal→401) passed in panel-v1.2.0 deploy. |
| AC-2 — parser unit test covers accept/reject | **MET** | `describe("checkInternalRejected…")` asserts 401 ok; 200/202/404/409/error/null all fail (panel-auth-check.test.ts:283-305); fixtures include `internalProbe: INTERNAL_OK` in the full-gate pass case (:42). Suite passes (53/53 in the two files run). |
| AC-3 — `shellcheck` clean on the wrapper | **MET (NOT VERIFIABLE-HERE directly / CI-asserted)** | CI `panel-quality` runs `shellcheck scripts/verify-panel-auth.sh` (README CI section); user-supplied evidence: main CI passed on 58c1d1c+. Not re-run here (no shellcheck invocation in this read-only pass). |

Spec SD-A4 honored; FR26 / AC3 (mechanized) / AC14 (boundary split) covered.

**Overall: CLOSE.**

---

## Follow-up items

- **F1 (Minor, #271) — IAM SES policy not committed.** No `ses:SendEmail`/`ses:SendRawEmail`
  policy document exists under `infra/`. Add the policy doc (scoped to the verified sender ARN,
  never `*`) and an `infra/changes/<date>-ses-digest-grant/` record so the live grant is
  reproducible/reversible. Route to `infra-engineer`. Live grant itself is NOT VERIFIABLE-HERE.
- **F2 (Minor, #271) — runbook SES/digest section missing.** `docs/runbooks/panel-deployment.md`
  has no `NOTIFICATION_SENDER`/`NOTIFICATION_RECIPIENT` secret-set step nor SES-verified-identity
  step; FR-49a (runbook-with-infra-change) appears unmet. Route to `technical-writer`.
- **F3 (Minor, operational) — the 12:58:21Z digest `UNAUTHORIZED`.** The production digest tick
  logged one `UNAUTHORIZED` immediately before the `empty_window` success at 12:58:23Z. This is
  consistent with a transient secret-propagation / cron-race on the first call rather than a
  defect: the endpoint is fail-closed by design (digest/route.ts step 1), and the subsequent call
  the same window succeeded. Recommend confirming the shared-secret is set in Fly for the digest
  path and that the first failing call was a one-off, not a recurring 401 every tick. Operational
  check only — no code change implied. In-scope to flag; root-causing is live/operator work.
- **F4 (housekeeping, #271) — no route-level L1 `digest.test.ts`.** Plan task 11.1 named a
  `digest.test.ts` for the route's selection/empty→204/exactly-once logic; the equivalent coverage
  exists split across `ses.test.ts` (render/send) and `digest-marking.test.ts` (L2.5 selection +
  mark-on-confirmed-send). Behavioral coverage is adequate; a thin route-handler unit test would
  close the plan-vs-delivered naming gap. Non-blocking. Route to `qa-engineer` if desired.

> Note: all drift above is **non-blocking** to issue/PR completion and does not replace the
> standard quality gates. Drift findings should be routed to `product-engineer`'s
> `activity-drift-reconciliation` for write-back; this report performs no write-back itself.

---

ISSUE #267: CLOSE — all 3 ACs MET on main, L2.5 tests present
ISSUE #268: CLOSE — all 4 ACs MET on main, block/clear/supersede tested
ISSUE #269: CLOSE — all 3 ACs MET; atomic trip + reset verified
ISSUE #270: CLOSE — all 4 ACs MET; idempotent sweep feeds G3/G5
ISSUE #271: CLOSE-WITH-FOLLOW-UP — code MET; IAM/runbook SES not in repo
ISSUE #272: CLOSE — all 3 ACs MET; internal→401 gate wired and tested
