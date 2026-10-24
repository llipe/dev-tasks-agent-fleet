# Result: 20261024-bug-fix-spike-probe

| Step | Status | Backup id | Restore command | Verified at | Evidence |
| ---- | ------ | --------- | --------------- | ----------- | -------- |
| 1 — deploy #443 image with `ALLOW_PROBE=1` | verified | `backup/runtime.before.json` (v1, image `f89566aa…`) | `rollback.sh --from 1` | 2026-10-24T13:49:00Z | runtime `bugfix_bug_fix-BiuPsdGSPK` **v2 READY**, image `…:5574194cb50aed7f…`, `ALLOW_PROBE=1`, roleArn unchanged (`agent-fleet-bug-fix-runtime`); the diff preview showed no IAM changes |
| 2 — probe run on the deployed runtime | applied, **verdict FAIL (sandbox/isolation)** | n/a | n/a | 2026-10-24T13:56:20Z | `backup/probe-run-1.sse` (leak scan 0 hits). **10 PASS / 22 FAIL.** Root cause, the same for all 22 failures: AgentCore runs the container with **`no_new_privs` set**, so `sudo` (setuid) can't run: "The 'no new privileges' flag is set, which prevents sudo from running as root". D-109's wrapper→fixer switch therefore can't work on AgentCore, and nothing downstream (sandbox, network, /proc, policy, `claude -p`) could be exercised. PASS: `srt`/CLI sandbox binaries present; wrapper can't become root; **board probe all PASS** (#5 detected; add idempotent; In progress/In review/Ready read back; cleanup: card deleted, issue `llipe/dev-tasks#324` closed, both confirmed afterwards); board disabled without PAT. Versions: Claude Code 2.1.309, sandbox-runtime 0.0.81. |

status: in-progress (steps 1–2 of 4; spike verdict FAIL on sandbox/isolation, board PASS)
