### Verification summary (local, CI-equivalent env)

Reproduced the CI env against the real local Supabase stack — server-only names **plus** the newly-exported `NEXT_PUBLIC_*` pair, `CI=true`, `REQUIRE_LOCAL_DB=1`.

**Root-cause confirmation:** before the fix the webServer 500'd on `GET /login` (`AuthConfigError: NEXT_PUBLIC_SUPABASE_URL is not set`) and `auth.setup.ts` timed out. After the fix, `GET /login` returns `200` and the `setup` project signs the operator in.

| Gate | Result |
| --- | --- |
| `pnpm --filter panel run test:e2e` | **PASS** — 19/19 (setup + all 7 auth scenarios incl. logout + invoke/live-tail/stale/artifact) |
| `pnpm --filter panel run validate` | **PASS** — lint + format:check + typecheck + test (950 passed / 4 skipped) + audit; Layer 2.5 ran for real |
| `pnpm --filter panel run build` | **PASS** — `next build` green |
| `make validate` (repo root) | **PASS** — Python 452 passed; JS/TS 951 passed / 4 skipped; `validate: all gates passed` |

Notes:
- Locally the bundled `chromium_headless_shell` was unavailable, so the E2E run used the documented `PW_CHANNEL=chrome` fallback. CI uses the pinned bundled chromium (installed via `playwright install --with-deps chromium`) — no config difference.
- No `stream-e2e`/SD6 cold-Realtime flake observed (Realtime warmed as CI does).
- **SD2 preserved:** only the anon URL + anon key are `NEXT_PUBLIC_*`; the service-role key never gets a `NEXT_PUBLIC_` twin.

Failing CI reference: https://github.com/llipe/dev-tasks-agent-fleet/actions/runs/34406811655
