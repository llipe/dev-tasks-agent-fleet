# Operator Worksheet — Issue #101: Complete #94 AC5/AC6 Reaper Verification

> **Who runs this:** the human operator with **Supabase SQL Editor** + **AWS** (AgentCore CLI, CloudWatch, `us-east-1`) access.
> **What it is:** a copy-paste, execute-in-order worksheet for the `[MANUAL]` steps of
> `workstream/tasks-issue-101-reaper-verification-residual.md`. Every block is transcribed from
> `docs/runbooks/issue-94-reaper-verification.md`; if anything here disagrees with the runbook, the
> runbook wins.
> **After you finish:** hand the filled-in "RECORD" slots back to `developer`, who transcribes them
> into the runbook results tables and both traceability matrices (the `[DEV]` steps), then closes #94.

---

## 0 — Before you start (read once)

**Two prerequisites bite on every real invocation** (steps in Parts C and D):

1. **Insert the `queued` `runs` row BEFORE invoking** (D1 / [#100](https://github.com/llipe/dev-tasks-agent-fleet/issues/100)). A direct `agentcore invoke` does **not** create the row — the agent only PATCHes it. Skip this and the run is invisible (PostgREST returns HTTP 200 on a zero-match UPDATE).
2. **Use the bare inner JSON via `--prompt-file`** ([#97](https://github.com/llipe/dev-tasks-agent-fleet/issues/97)). Do not hand-wrap it in `{"prompt": ...}`.

**Golden rules:**
- The reaper is already scheduled (`reap-stale-runs`, `* * * * *`). "Wait one tick" = up to 60 s.
- **Never leave `SUPABASE_URL` broken** (Part D) — restore it or every later check silently fails.
- Clean up each synthetic row when its check is done (`run_events` cascade-delete with it).
- All timestamps are UTC.

**Sanity check the reaper is alive before anything else:**

```sql
select jobid, jobname, schedule, active
from cron.job
where jobname = 'reap-stale-runs';
-- expect: one row, schedule '* * * * *', active = t
```

```sql
select status, start_time
from cron.job_run_details
where jobid = (select jobid from cron.job where jobname = 'reap-stale-runs')
order by start_time desc
limit 3;
-- expect: recent rows, status = 'succeeded'
```

If the job is missing, re-run `select cron.schedule('reap-stale-runs', '* * * * *', $$select reap_stale_runs()$$);` and stop — something reset it.

---

## Part A — AC1: `queued → failed_to_start` view leads the reaper

Closes #94 AC4 (`queued` half). Maps to task steps **1.1–1.4**. Runbook §2.2/§2.3. ~2 min.

### A1 (task 1.1) — Insert a past-threshold `queued` row

```sql
insert into runs (
  id, agent_id, agent_version, repository_id, installation_id,
  status, queued_at, max_runtime_seconds, grace_seconds, start_timeout_seconds
)
select
  gen_random_uuid(), a.id, a.version, r.id, r.installation_id,
  'queued', now() - interval '90 seconds', 3600, 120, 60
from agents a
join repositories r on r.full_name = 'llipe/memo-cli'
where a.slug = 'dependency-update'
returning id;
```

> `queued_at` is backdated 90 s and `start_timeout_seconds = 60`, so the row is already past threshold — you observe the read-time layer *immediately*, before the next tick materializes it.

**RECORD — A_ID = `7a4a74f4-a5aa-4c46-8e63-b92e99fc8813`**

### A2 (task 1.2) — Query the view IMMEDIATELY (before the next tick)

Paste your `A_ID` in place of `:id`:

```sql
select status, effective_status from v_runs where id = ':id';
```

- **Expected:** `status = 'queued'` **and** `effective_status = 'failed_to_start'` (simultaneously).

**RECORD — observed:** `status = queued`, `effective_status = failed_to_start`

> **If the tick already fired** (both columns read `failed_to_start`), you missed the window. Recover with the runbook §3.3 pattern, then **re-schedule** (forgetting to re-schedule breaks every later check):
> ```sql
> select cron.unschedule('reap-stale-runs');
> -- re-run A1, then A2 immediately
> select cron.schedule('reap-stale-runs', '* * * * *', $$select reap_stale_runs()$$);
> ```

### A3 — (optional) confirm it then materializes + event schema (CT-3 / EC-9)

Wait one tick, then:

```sql
select status, error_code, error_message, finished_at from runs where id = ':id';
-- expect: failed_to_start / START_TIMEOUT / non-null message + finished_at

select seq, level, message,
       data->>'reaped_by' as reaped_by,
       data->>'reason'    as reason
from run_events where run_id = ':id' order by seq;
-- expect: level='error', reaped_by='reap_stale_runs', reason='START_TIMEOUT', seq = max(seq)+1
```

**RECORD — materialized status:** `failed_to_start`  · **event reason:** `START_TIMEOUT`  · **event seq:** `1`

### A4 (task 1.3) — Cleanup

```sql
delete from runs where id = ':id';   -- events cascade
```

- [x] **Part A done** — AC1 observed.

---

## Part B — AC2: interlock (healthy long run not reaped, reaps past threshold)

Closes #94 AC5 interlock + dep-update AC-36 dynamic half. Maps to task steps **1.5–1.9**. Runbook §4.4. ~10 min. **Depends on nothing (#98 not required).**

### B1 (task 1.5) — Insert a healthy `running` row with REAL thresholds

```sql
insert into runs (
  id, agent_id, agent_version, repository_id, installation_id,
  status, queued_at, started_at, max_runtime_seconds, grace_seconds, start_timeout_seconds
)
select
  gen_random_uuid(), a.id, a.version, r.id, r.installation_id,
  'running', now() - interval '31 min', now() - interval '30 min', 3600, 120, 300
from agents a
join repositories r on r.full_name = 'llipe/memo-cli'
where a.slug = 'dependency-update'
returning id;
```

> Real thresholds (3600/120 → boundary 3720 s). `started_at` is 30 min ago — well under the boundary, so a correct reaper must NOT touch it (EC-2 / EC-4).

**RECORD — B_ID = `b0e33d0d-ff90-468e-b32e-95f80cd469d1`**

### B2 (task 1.6) — Across SEVERAL ticks, confirm it stays healthy

Run this a few times over ~3–5 minutes (spanning multiple cron ticks). Paste `B_ID` for `:id`:

```sql
select status, effective_status from v_runs where id = ':id';
-- expect EVERY time: running | running

select count(*) as reaper_events
from run_events
where run_id = ':id' and data->>'reaped_by' = 'reap_stale_runs';
-- expect EVERY time: 0
```

**RECORD — observations (tick-by-tick):**

| Check # | time (UTC) | status | effective_status | reaper_events |
|---------|-----------|--------|------------------|---------------|
| 1 | 17:40 | running | running | 0 |
| 2 | 17:45 | running | running | 0 |
| 3 | 17:51 | running | running | 0 |

### B3 (task 1.7) — Now push it past the boundary and confirm it DOES reap

```sql
update runs set started_at = now() - interval '63 min' where id = ':id';
-- 63 min = 3780 s > 3720 s boundary
```

Wait one tick, then:

```sql
select status, error_code, error_message, finished_at from runs where id = ':id';
-- expect: timed_out / RUNTIME_TIMEOUT / non-null message + finished_at

select seq, level, data->>'reason' as reason, data->>'reaped_by' as reaped_by
from run_events where run_id = ':id' and data->>'reaped_by' = 'reap_stale_runs' order by seq;
-- expect: exactly one row, reason = RUNTIME_TIMEOUT
```

**RECORD — status after boundary:** `RUNTIME_TIMEOUT`  · **error_code:** `RUNTIME_TIMEOUT`  · **# reaper events:** `1`

### B4 (task 1.8) — Cleanup

```sql
delete from runs where id = ':id';
```

- [x] **Part B done** — interlock proven in both directions (un-reaped while healthy, reaped past 3720 s).

---

## Part C — AC3: valid cold-start measurement

Closes #94 AC5 cold-start half; resolves dep-update PRD open question 8. Maps to task steps **1.10–1.14**. Runbook §4.0/§4.1/§4.3. ~5 min. **Needs *a* real invocation, not a long one.**

> ⚠️ The previously recorded **185.7 s figure is INVALID** — it included human delay between the manual INSERT and the invoke. Measure the gap with the `date -u` method below, NOT `started_at − queued_at`.

### C1 (task 1.10) — Pre-insert the `queued` row (D1 / #100)

```sql
insert into runs (
  id, agent_id, agent_version, repository_id, installation_id,
  status, queued_at, max_runtime_seconds, grace_seconds, start_timeout_seconds
)
select gen_random_uuid(), a.id, a.version, r.id, r.installation_id,
       'queued', now(), 3600, 120, 300
from agents a
join repositories r on r.full_name = 'llipe/tf-ecommerce-mgmt'
where a.slug = 'dependency-update'
returning id;
```

**RECORD — C_ID = `67cdff91-1bdb-4b4c-a33a-bf1e03b1e86d`**

### C2 — Write the bare-payload invoke file

Create `/tmp/invoke-94.json` with your `C_ID` as `run_id` (no `prompt` wrapper key):

```json
{"run_id": "<C_ID>", "repository_org": "llipe", "repository_name": "tf-ecommerce-mgmt", "params": {"fix_mode": "llm_fix", "max_fix_attempts": 3}}
```

> `repository_name` is the repo name only — not `org/repo`.

### C3 (task 1.11) — Record the invoke timestamp, then invoke

```bash
cd agents/dependency-update
date -u +"%Y-%m-%dT%H:%M:%S.%3NZ"        # <-- RECORD this exact value (T_invoke)
agentcore invoke --prompt-file /tmp/invoke-94.json
```

**RECORD — T_invoke = `2026-09-01T22:00:28.3NZ`** (the `date -u` output)

Confirm it started (paste `C_ID`):

```sql
select status, started_at from runs where id = ':id';
-- expect: running (or later terminal) + non-null started_at
```

**RECORD — started_at = `2026-09-01 22:00:32.506273+00`**

### C4 (task 1.12) — Compute the TRUE cold-start gap

```
cold_start_gap = started_at  −  T_invoke        <-- the valid figure
(do NOT use started_at − queued_at on a hand-inserted row)
```

Optionally also record the confounded figure for contrast, clearly labelled:

```sql
select queued_at, started_at,
       extract(epoch from (started_at - queued_at)) as insert_to_start_seconds_INVALID
from runs where id = ':id';
```

**RECORD — TRUE cold_start_gap (started_at − T_invoke) = `4.21 s`**
**RECORD — vs `grace_seconds = 120`: comfortably under? `YES`**
**RECORD — PRD open question 8 disposition: `resolved (grace 120 adequate)`**

### C5 (task 1.13) — Cleanup (if this was a throwaway measurement run)

```sql
delete from runs where id = ':id';
```

- [x] **Part C done** — valid cold-start gap recorded.

---

## Part D — AC4: CloudWatch fallback when Supabase is unreachable

Closes #94 AC6. Maps to task steps **1.15–1.20**. Runbook §5. ~15 min.

### D1 (task 1.15) — Record the correct `SUPABASE_URL`, then break it

The value lives in `agents/dependency-update/agentcore/agentcore.json` under `runtimes[].envVars`.

**RECORD — correct SUPABASE_URL = `https://hegxeycmbmjfgzqpdiik.supabas.co`**

Point it at an unreachable host on the runtime config (e.g. `https://10.255.255.1` or a bogus subdomain), per runbook §5.1. Apply the config change to the AgentCore runtime.

- [x] SUPABASE_URL pointed at an unreachable host.

### D2 (task 1.16) — Pre-insert a `queued` row, then invoke

```sql
insert into runs (
  id, agent_id, agent_version, repository_id, installation_id,
  status, queued_at, max_runtime_seconds, grace_seconds, start_timeout_seconds
)
select gen_random_uuid(), a.id, a.version, r.id, r.installation_id,
       'queued', now(), 3600, 120, 300
from agents a
join repositories r on r.full_name = 'llipe/tf-ecommerce-mgmt'
where a.slug = 'dependency-update'
returning id;
```

**RECORD — D_ID = `378e8636-acd6-4ed4-8749-64474226ed2f`**

Update `/tmp/invoke-94.json` `run_id` to `D_ID`, record the timestamp, invoke:

```bash
cd agents/dependency-update
date -u +"%Y-%m-%dT%H:%M:%S.%3NZ"
agentcore invoke --prompt-file /tmp/invoke-94.json
```

### D3 (task 1.17) — Assert the agent COMPLETES (does not crash)

The invocation should return/exit normally — reporting failure must never kill the agent.

**RECORD — agent completed without crashing? `YES / NO`**

### D4 (task 1.18) — Assert payloads reached CloudWatch via stderr

After the SDK's 3 retries (`HTTP_RETRIES = 3`), failed payloads are dumped to stderr → CloudWatch:

```bash
aws logs tail /aws/bedrock-agentcore/<runtime-log-group> \
  --since 15m --region us-east-1 --format short \
  | grep -iE "supabase|retry|payload|report"
```

- **Expected:** lines showing retry attempts and the dumped payload(s).
- **Note (EC-8):** only transient/network/5xx failures are retried 3× then dumped; a 4xx contract error is **not** retried. The unreachable-host case here is the transient path.

**RECORD — CloudWatch shows dumped payloads after retries? `YES`** (paste 1–2 representative log lines)

```log
» aws logs tail /aws/bedrock-agentcore/runtimes/dependencyupdate_dependency_update-UsQc5U5Yz0-DEFAULT --since 15m --region us-east-1 --format short | grep -iE "supabase|retry|payload|report" 
2026-09-02T13:06:52 [agent_reporter] fallo al escribir PATCH /runs?id=eq.378e8636-acd6-4ed4-8749-64474226ed2f: URLError(gaierror(-2, 'Name or service not known'))
2026-09-02T13:06:54 [agent_reporter] fallo al escribir POST /run_events: URLError(gaierror(-2, 'Name or service not known'))
2026-09-02T13:06:54 [agent_reporter] payload perdido: [{"run_id": "378e8636-acd6-4ed4-8749-64474226ed2f", "step_id": null, "seq": 1, "ts": "2026-09-02T13:06:52.680598+00:00", "level": "info", "message": "Ejecuci\u00f3n iniciada.", "data": {}}]
2026-09-02T13:06:55 [agent_reporter] fallo al escribir POST /run_steps: URLError(gaierror(-2, 'Name or service not known'))
2026-09-02T13:06:55 [agent_reporter] payload perdido: [{"id": "2cc1a5c2-c5df-4277-8305-e2b70dae8609", "run_id": "378e8636-acd6-4ed4-8749-64474226ed2f", "seq": 1, "key": "resolve_credentials", "title": null, "status": "running", "started_at": "2026-09-02T13:06:54.185352+00:00"}]
2026-09-02T13:06:57 [agent_reporter] fallo al escribir POST /run_events: URLError(gaierror(-2, 'Name or service not known'))
2026-09-02T13:06:57 [agent_reporter] payload perdido: [{"run_id": "378e8636-acd6-4ed4-8749-64474226ed2f", "step_id": "2cc1a5c2-c5df-4277-8305-e2b70dae8609", "seq": 2, "ts": "2026-09-02T13:06:55.694488+00:00", "level": "error", "message": "Traceback (most recent call last):\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connection.py\", line 204, in _new_conn\n    sock = connection.create_connection(\n        (self._dns_host, self.port),\n    ...<2 lines>...\n        socket_options=self.socket_options,\n    )\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/util/connection.py\", line 60, in create_connection\n    for res in socket.getaddrinfo(host, port, family, socket.SOCK_STREAM):\n               ~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/usr/local/lib/python3.13/socket.py\", line 983, in getaddrinfo\n    for res in _socket.getaddrinfo(host, port, family, type, proto, flags):\n               ~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\nsocket.gaierror: [Errno -2] Name or service not known\n\nThe above exception was the direct cause of the following exception:\n\nTraceback (most recent call last):\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connectionpool.py\", line 788, in urlopen\n    response = self._make_request(\n        conn,\n    ...<10 lines>...\n        **response_kw,\n    )\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connectionpool.py\", line 488, in _make_request\n    raise new_e\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connectionpool.py\", line 464, in _make_request\n    self._validate_conn(conn)\n    ~~~~~~~~~~~~~~~~~~~^^^^^^\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connectionpool.py\", line 1106, in _validate_conn\n    conn.connect()\n    ~~~~~~~~~~~~^^\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connection.py\", line 759, in connect\n    self.sock = sock = self._new_conn()\n                       ~~~~~~~~~~~~~~^^\n  File \"/usr/local/lib/python3.13/site-packages/urlli
2026-09-02T13:06:58 [agent_reporter] fallo al escribir PATCH /run_steps?id=eq.2cc1a5c2-c5df-4277-8305-e2b70dae8609: URLError(gaierror(-2, 'Name or service not known'))
2026-09-02T13:06:58 [agent_reporter] payload perdido: {"status": "failed", "finished_at": "2026-09-02T13:06:55.694467+00:00", "error_message": "Traceback (most recent call last):\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connection.py\", line 204, in _new_conn\n    sock = connection.create_connection(\n        (self._dns_host, self.port),\n    ...<2 lines>...\n        socket_options=self.socket_options,\n    )\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/util/connection.py\", line 60, in create_connection\n    for res in socket.getaddrinfo(host, port, family, socket.SOCK_STREAM):\n               ~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/usr/local/lib/python3.13/socket.py\", line 983, in getaddrinfo\n    for res in _socket.getaddrinfo(host, port, family, type, proto, flags):\n               ~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\nsocket.gaierror: [Errno -2] Name or service not known\n\nThe above exception was the direct cause of the following exception:\n\nTraceback (most recent call last):\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connectionpool.py\", line 788, in urlopen\n    response = self._make_request(\n        conn,\n    ...<10 lines>...\n        **response_kw,\n    )\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connectionpool.py\", line 488, in _make_request\n    raise new_e\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connectionpool.py\", line 464, in _make_request\n    self._validate_conn(conn)\n    ~~~~~~~~~~~~~~~~~~~^^^^^^\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connectionpool.py\", line 1106, in _validate_conn\n    conn.connect()\n    ~~~~~~~~~~~~^^\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connection.py\", line 759, in connect\n    self.sock = sock = self._new_conn()\n                       ~~~~~~~~~~~~~~^^\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connection.py\", line 211, in _new_conn\n    raise NameResolutionError(self.host, self, e) f
2026-09-02T13:07:00 [agent_reporter] fallo al escribir POST /run_events: URLError(gaierror(-2, 'Name or service not known'))
2026-09-02T13:07:00 [agent_reporter] payload perdido: [{"run_id": "378e8636-acd6-4ed4-8749-64474226ed2f", "step_id": null, "seq": 3, "ts": "2026-09-02T13:06:58.733472+00:00", "level": "error", "message": "Traceback (most recent call last):\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connection.py\", line 204, in _new_conn\n    sock = connection.create_connection(\n        (self._dns_host, self.port),\n    ...<2 lines>...\n        socket_options=self.socket_options,\n    )\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/util/connection.py\", line 60, in create_connection\n    for res in socket.getaddrinfo(host, port, family, socket.SOCK_STREAM):\n               ~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/usr/local/lib/python3.13/socket.py\", line 983, in getaddrinfo\n    for res in _socket.getaddrinfo(host, port, family, type, proto, flags):\n               ~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\nsocket.gaierror: [Errno -2] Name or service not known\n\nThe above exception was the direct cause of the following exception:\n\nTraceback (most recent call last):\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connectionpool.py\", line 788, in urlopen\n    response = self._make_request(\n        conn,\n    ...<10 lines>...\n        **response_kw,\n    )\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connectionpool.py\", line 488, in _make_request\n    raise new_e\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connectionpool.py\", line 464, in _make_request\n    self._validate_conn(conn)\n    ~~~~~~~~~~~~~~~~~~~^^^^^^\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connectionpool.py\", line 1106, in _validate_conn\n    conn.connect()\n    ~~~~~~~~~~~~^^\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connection.py\", line 759, in connect\n    self.sock = sock = self._new_conn()\n                       ~~~~~~~~~~~~~~^^\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connection.py\", line 211, in _
2026-09-02T13:07:01 [agent_reporter] fallo al escribir POST /run_events: URLError(gaierror(-2, 'Name or service not known'))
2026-09-02T13:07:01 [agent_reporter] payload perdido: [{"run_id": "378e8636-acd6-4ed4-8749-64474226ed2f", "step_id": null, "seq": 4, "ts": "2026-09-02T13:07:00.236192+00:00", "level": "info", "message": "Ejecuci\u00f3n finalizada: failed", "data": {}}]
2026-09-02T13:07:03 [agent_reporter] fallo al escribir PATCH /runs?id=eq.378e8636-acd6-4ed4-8749-64474226ed2f: URLError(gaierror(-2, 'Name or service not known'))
2026-09-02T13:07:03 [agent_reporter] payload perdido: {"status": "failed", "finished_at": "2026-09-02T13:07:01.738979+00:00", "error_code": "ConnectionError", "error_message": "HTTPSConnectionPool(host='hegxeycmbmjfgzqpdiik.supabasfake.co', port=443): Max retries exceeded with url: /rest/v1/github_installations?github_org_slug=eq.llipe&is_enabled=eq.true&select=app_id,installation_id,private_key_secret_arn (Caused by NameResolutionError(\"HTTPSConnection(host='hegxeycmbmjfgzqpdiik.supabasfake.co', port=443): Failed to resolve 'hegxeycmbmjfgzqpdiik.supabasfake.co' ([Errno -2] Name or service not known)\"))"}
2026-09-02T13:07:03 {"timestamp": "2026-09-02T13:07:03.249Z", "level": "ERROR", "message": "Unhandled exception:\nTraceback (most recent call last):\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connection.py\", line 204, in _new_conn\n    sock = connection.create_connection(\n        (self._dns_host, self.port),\n    ...<2 lines>...\n        socket_options=self.socket_options,\n    )\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/util/connection.py\", line 60, in create_connection\n    for res in socket.getaddrinfo(host, port, family, socket.SOCK_STREAM):\n               ~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/usr/local/lib/python3.13/socket.py\", line 983, in getaddrinfo\n    for res in _socket.getaddrinfo(host, port, family, type, proto, flags):\n               ~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\nsocket.gaierror: [Errno -2] Name or service not known\n\nThe above exception was the direct cause of the following exception:\n\nTraceback (most recent call last):\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connectionpool.py\", line 788, in urlopen\n    response = self._make_request(\n        conn,\n    ...<10 lines>...\n        **response_kw,\n    )\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connectionpool.py\", line 488, in _make_request\n    raise new_e\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connectionpool.py\", line 464, in _make_request\n    self._validate_conn(conn)\n    ~~~~~~~~~~~~~~~~~~~^^^^^^\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connectionpool.py\", line 1106, in _validate_conn\n    conn.connect()\n    ~~~~~~~~~~~~^^\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connection.py\", line 759, in connect\n    self.sock = sock = self._new_conn()\n                       ~~~~~~~~~~~~~~^^\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connection.py\", line 211, in _new_conn\n    raise NameResolutionError(self.host, self, e) from e\nurllib3.exceptions.NameResolutionError: HTTPSConnection(host='hegxeycmbmjfgzqpdiik.supabasfake.co', port=443): Failed to resolve 'hegxeycmbmjfgzqpdiik.supabasfake.co' ([Errno -2] Name or service not known)\n\nThe above exception was the direct cause of the following exception:\n\nTraceback (most recent call last):\n  File \"/usr/local/lib/python3.13/site-packages/requests/adapters.py\", line 696, in send\n    resp = conn.urlopen(\n        method=request.method,\n    ...<9 lines>...\n        chunked=chunked,\n    )\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/connectionpool.py\", line 842, in urlopen\n    retries = retries.increment(\n        method, url, error=new_e, _pool=self, _stacktrace=sys.exc_info()[2]\n    )\n  File \"/usr/local/lib/python3.13/site-packages/urllib3/util/retry.py\", line 543, in increment\n    raise MaxRetryError(_pool, url, reason) from reason  # type: ignore[arg-type]\n    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\nurllib3.exceptions.MaxRetryError: HTTPSConnectionPool(host='hegxeycmbmjfgzqpdiik.supabasfake.co', port=443): Max retries exceeded with url: /rest/v1/github_installations?github_org_slug=eq.llipe&is_enabled=eq.true&select=app_id,installation_id,private_key_secret_arn (Caused by NameResolutionError(\"HTTPSConnection(host='hegxeycmbmjfgzqpdiik.supabasfake.co', port=443): Failed to resolve 'hegxeycmbmjfgzqpdiik.supabasfake.co' ([Errno -2] Name or service not known)\"))\n\nDuring handling of the above exception, another exception occurred:\n\nTraceback (most recent call last):\n  File \"/app/main.py\", line 552, in invoke\n    token_ctx = resolve_github_credentials(org)\n  File \"/app/credentials.py\", line 149, in resolve_github_credentials\n    row = _get_installation(org, url, key)\n  File \"/app/credentials.py\", line 76, in _get_installation\n    resp = requests.get(url, headers=headers, timeout=15)\n  File \"/usr/local/lib/python3.13/site-packages/requests/api.py\", line 87, in get\n    return request(\"get\", url, params=params, **kwargs)\n  File \"/usr/local/lib/python3.13/site-packages/requests/api.py\", line 71, in request\n    return session.request(method=method, url=url, **kwargs)\n           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/usr/local/lib/python3.13/site-packages/requests/sessions.py\", line 651, in request\n    resp = self.send(prep, **send_kwargs)\n  File \"/usr/local/lib/python3.13/site-packages/requests/sessions.py\", line 784, in send\n    r = adapter.send(request, **kwargs)\n  File \"/usr/local/lib/python3.13/site-packages/requests/adapters.py\", line 729, in send\n    raise ConnectionError(e, request=request)\nrequests.exceptions.ConnectionError: HTTPSConnectionPool(host='hegxeycmbmjfgzqpdiik.supabasfake.co', port=443): Max retries exceeded with url: /rest/v1/github_installations?github_org_slug=eq.llipe&is_enabled=eq.true&select=app_id,installation_id,private_key_secret_arn (Caused by NameResolutionError(\"HTTPSConnection(host='hegxeycmbmjfgzqpdiik.supabasfake.co', port=443): Failed to resolve 'hegxeycmbmjfgzqpdiik.supabasfake.co' ([Errno -2] Name or service not known)\"))\n", "logger": "bedrock_agentcore.app", "requestId": "a6e4e6e4-3743-4e26-a7df-71d345c600d3", "sessionId": "3e371849-05ab-4f44-aeda-1c28473b0da7"}
```

### D5 (task 1.19) — ⚠️ RESTORE `SUPABASE_URL` and verify reporting resumes

Restore the value you recorded in D1 to the runtime config and re-apply.

Invoke once more (new pre-inserted row, or reuse the flow), then confirm a run reports normally:

```sql
select status from runs where id = ':new_id';   -- should update to running/terminal normally again
```

**RECORD — SUPABASE_URL restored? `YES`  · normal reporting resumed? `YES / NO`**

> If you ever later see a pre-inserted row reaped `failed_to_start` with `started_at = null` and zero agent events, check THIS first — it means the URL is still broken.

### D6 — Cleanup

```sql
delete from runs where id in (':D_ID', ':new_id');
```

- [ ] **Part D done** — agent survived unreachable Supabase, payloads recoverable, URL restored.

---

## Part E — Closeout gate (AC6, task 1.26)

This is the only remaining `[MANUAL/DEV]` decision; the `[DEV]` transcription (steps 1.21–1.25, 1.27) is done by `developer` from your RECORD slots.

- [x] Confirm all **7** of #94's ACs read PASS (AC1–AC4, AC7 already PASS from #94; AC5 from Parts B+C; AC6 from Part D).
- [x] Hand this filled worksheet to `developer` for transcription into the runbook + both matrices.
- [x] Only after the matrices show 7/7 and the PR is merged: close #94 (delegate the close + evidence comment to `github-ops`).

---

## Results summary (fill in, then hand back)

| Check | Task | Result | Verdict |
|-------|------|--------|---------|
| A2 — `queued` view split | 1.2 | status=____ / eff=____ | PASS / FAIL |
| B2 — healthy un-reaped across ticks | 1.6 | reaper_events all 0? ____ | PASS / FAIL |
| B3 — reaps past 3720 s | 1.7 | status=____ | PASS / FAIL |
| C4 — true cold-start gap | 1.12 | ____ s vs grace 120 | PASS / FAIL |
| D3 — agent completes | 1.17 | ____ | PASS / FAIL |
| D4 — CloudWatch payloads | 1.18 | ____ | PASS / FAIL |
| D5 — SUPABASE_URL restored | 1.19 | ____ | PASS / FAIL |

**Invalid figure reminder:** do NOT record `started_at − queued_at` (or the old 185.7 s) as the cold-start gap. Only the `started_at − T_invoke` value from C4 counts.
