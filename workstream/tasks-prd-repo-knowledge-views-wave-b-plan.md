# Implementation Plan - Repository Knowledge Views, Wave B (read path)

Source: `workstream/user-stories-prd-repo-knowledge-views.md` (v1.1), S-219–S-225
PRD `docs/requirements/prd-repo-knowledge-views.md` v1.2 · spec `workstream/specification-prd-repo-knowledge-views.md` v1.0 · decisions `workstream/decisions-repo-knowledge-views.md`

> Note: Integration branch `integration/repo-knowledge-wave-b`, one PR per story into it. S-219 runs through `/infra-engineer` (one approved step at a time) and must be applied before the Wave B deploy, not before the code merges (D-30). Packages come from the `docs/tech.md` Package Map: `panel`. Infra and docs use `[repo root]`.

## Relevant Files

- `infra/changes/<date>-panel-github-contents-read/**` - Infra change record (plan, commands, result, rollback, backup)
- `infra/agentcore-invoke-policy.json` - Panel role policy, kept in step with live
- `infra/environments.yaml` - Fix the stale OIDC comment (line 51)
- `docs/runbooks/panel-github-read.md` - New runbook (FR-49a)
- `docs/runbooks/README.md` - Runbook index
- `panel/lib/github/app-token.ts` - Read-only, single-repository token minting
- `panel/lib/github/errors.ts` - `CredentialError`, `TokenScopeError`, `Upstream`, codes
- `panel/lib/github/client.ts` - `fetch` wrapper (timeout, API version, raw Accept)
- `panel/lib/knowledge/reader.ts` - `resolveHead`, `readArtifact`
- `panel/lib/knowledge/lru.ts` - 64 MB byte-bounded LRU
- `panel/lib/knowledge/staleness.ts` - Field-guide staleness
- `panel/lib/knowledge/path.ts` - Path normaliser
- `panel/lib/knowledge/csp.ts` - D-23 header builder
- `panel/lib/knowledge/content-type.ts` - Extension allowlist
- `panel/lib/knowledge/graph.ts` - Graph read and validation
- `panel/lib/schema/graph-v1.schema.json` - `graph.json` v1 contract (spec §5.1)
- `panel/lib/supabase/queries.ts` - Installation-row read
- `panel/proxy.ts` - Matcher fix
- `panel/proxy.matcher.test.ts` - Matcher path table
- Release-gate script (path per `docs/runbooks/panel-deployment.md`) - Two 401 assertions
- `panel/app/api/repositories/[id]/field-guide/[sha]/[...path]/route.ts` - Field-guide route
- `panel/app/api/repositories/[id]/graph/[sha]/route.ts` - Graph route
- `panel/app/(panel)/repositories/[id]/page.tsx`, `page.module.css` - Repository page
- `panel/components/Tabs.tsx` - Shared tabs
- `panel/components/ArtifactState.tsx` - Empty and error states
- `panel/components/repositories/RepositoryTable.tsx` - Name links to the page
- `panel/components/shell/Sidebar.tsx` - Prefix-active Repositories item
- `panel/tests/fixtures/graph/*.json` - Graph fixtures
- `DESIGN.md` - `Tabs`, `ArtifactState`, repository page layout
- Tests next to each module (`*.test.ts`, `*.test.tsx`)

## Tasks

- [ ] 1.0 Implement Story S-219 - https://github.com/llipe/dev-tasks-agent-fleet/issues/513: Panel role may read the App key
  - [ ] 1.1 [repo root] `/infra-engineer` plan: read `github_installations.private_key_secret_arn` and draft one statement, `secretsmanager:GetSecretValue` on that ARN only, for role `panel-agentcore-invoke` (D-14, D-30)
  - [ ] 1.2 [repo root] Back up the current inline policy to `backup/`. Write `plan.md`, `commands.sh`, `rollback.sh` in the `20261014-fly-oidc-issuer-trust` structure
  - [ ] 1.3 [repo root] **Confirmation gate:** present the plan and get explicit user approval before any apply step
  - [ ] 1.4 [repo root] Apply after approval and record `result.md`
  - [ ] 1.5 [repo root] Update `infra/agentcore-invoke-policy.json` to match live. Correct the stale OIDC comment at `infra/environments.yaml:51` to the subject in `infra/trust-policy.json:9` (D-19)
  - [ ] 1.6 [repo root] Write `docs/runbooks/panel-github-read.md` (verify, key-rotation effect with the 1 h cache, rollback) and add the index row (FR-49a)
  - [ ] 1.7 [repo root] Edge case: a wrong ARN fails closed (asserted in the simulation; the panel side is covered in 2.x)
  - [ ] 1.8 Verify Acceptance Criterion: exactly one new statement, no wildcard resource (FR-7)
  - [ ] 1.9 Verify Acceptance Criterion: change record complete
  - [ ] 1.10 Verify Acceptance Criterion: repo policy file matches live; comment fixed
  - [ ] 1.11 Verify Acceptance Criterion: runbook shipped in this PR
  - [ ] 1.12 Verify Acceptance Criterion: `aws iam simulate-principal-policy` allows `GetSecretValue` on the ARN and denies it on another secret. Output saved in `backup/`
  - [ ] 1.13 AC-to-test mapping: AC1, AC5 → simulation output; AC2–AC4 → review checklist
  - [ ] 1.14 Run Tests: simulation; `pnpm run validate` (docs and lint unaffected)

- [ ] 2.0 Implement Story S-220 - https://github.com/llipe/dev-tasks-agent-fleet/issues/514: Read-only installation token minting
  - [ ] 2.1 [panel] Write failing L1 tests: JWT claims (`iat = now−60`, `exp = now+540`, `iss = app_id`, RS256); scope checker (exact; broader permission; extra repository; missing field) (D-24)
  - [ ] 2.2 [panel] Write failing L2 tests with a fake Secrets Manager client and an injected fetch (D-24, D-29):
    - mint;
    - cache hit makes no second POST;
    - refresh inside the 5-minute window;
    - null ARN → `CredentialError`;
    - scope failure discards the token;
    - the token string is absent from errors and captured logs;
    - one in-flight mint per repository under concurrent first calls
  - [ ] 2.3 [panel] Add an installation-row read to `lib/supabase/queries.ts` (installation id, `app_id`, `private_key_secret_arn`)
  - [ ] 2.4 [panel] Implement `lib/github/app-token.ts` (`server-only`). PEM via the existing credential module with a 1 h cache. JWT via `node:crypto` (D-24)
  - [ ] 2.5 [panel] POST `/app/installations/{iid}/access_tokens` with `{"repositories":["<name>"],"permissions":{"contents":"read","metadata":"read"}}`. Check the response scope exactly, else throw `TokenScopeError` (D-14, D-24)
  - [ ] 2.6 [panel] Token cache per repository until `expires_at − 5 min`. Errors carry codes only (ADR-009)
  - [ ] 2.7 Verify Acceptance Criterion: installation row read; null ARN → `CredentialError`
  - [ ] 2.8 Verify Acceptance Criterion: JWT claims and algorithm
  - [ ] 2.9 Verify Acceptance Criterion: exact request body (FR-7)
  - [ ] 2.10 Verify Acceptance Criterion: broader grant discarded with `TokenScopeError`
  - [ ] 2.11 Verify Acceptance Criterion: cache lifetimes (token, PEM)
  - [ ] 2.12 Verify Acceptance Criterion: `server-only`; no token or PEM in messages or logs (FR-8, AC-9)
  - [ ] 2.13 AC-to-test mapping: AC1–AC6 → `app-token.test.ts` T-220-01…T-220-10
  - [ ] 2.14 Run Tests: `pnpm run test:unit`, `pnpm run validate`

- [ ] 3.0 Implement Story S-221 - https://github.com/llipe/dev-tasks-agent-fleet/issues/515: Artifact reader, cache and staleness
  - [ ] 3.1 [panel] Write failing L1 tests: LRU byte accounting and eviction order; staleness boundaries at 29/30/31 days and 99/100/101 commits (AC-6, D-11)
  - [ ] 3.2 [panel] Write failing L2 tests with an injected fetch (D-25):
    - 404 → `NotPresent`;
    - 401/403/429/5xx → `Upstream`;
    - a cache hit makes no fetch;
    - the HEAD cache expires at 60 s;
    - streaming stops at the cap → `TooLarge`;
    - empty file;
    - file exactly at the cap;
    - `commits?path` empty → `NotPresent`;
    - `ahead_by = 0`
  - [ ] 3.3 [panel] Implement `lib/github/client.ts`: 10 s timeout, `X-GitHub-Api-Version: 2022-11-28`, raw Accept, uses `tokenFor()`
  - [ ] 3.4 [panel] Implement `lib/knowledge/lru.ts`: 64 MB, key `(repoId, sha, path)`, no TTL, over-cap bodies never inserted (D-25)
  - [ ] 3.5 [panel] Implement `resolveHead()` on `repositories.default_branch`, cached 60 s, and `readArtifact()` with `contents?ref=sha` (D-06, D-25)
  - [ ] 3.6 [panel] Implement `staleness()`: `commits?path=docs/field-guide&sha=head&per_page=1`, then `compare/{guide}...{head}`; `warning = ageDays > 30 || commitsBehind > 100`; cached per `(repoId, headSha)` (D-11, D-25)
  - [ ] 3.7 [panel] One structured log line per fetch (repo, short SHA, path class, outcome, bytes, cache hit), with no token or upstream body
  - [ ] 3.8 Verify Acceptance Criterion: HEAD via the stored default branch, cached 60 s
  - [ ] 3.9 Verify Acceptance Criterion: status mapping and streaming cap (FR-6, FR-10)
  - [ ] 3.10 Verify Acceptance Criterion: LRU contract (FR-9)
  - [ ] 3.11 Verify Acceptance Criterion: staleness shape and rule (FR-15)
  - [ ] 3.12 Verify Acceptance Criterion: timeout and API version header
  - [ ] 3.13 Verify Acceptance Criterion: log line shape and redaction
  - [ ] 3.14 AC-to-test mapping: AC1–AC6 → `reader.test.ts`, `lru.test.ts`, `staleness.test.ts`
  - [ ] 3.15 Run Tests: `pnpm run test:unit`, `pnpm run validate`

- [ ] 4.0 Implement Story S-222 - https://github.com/llipe/dev-tasks-agent-fleet/issues/516: Gate every /api path; release gate
  - [ ] 4.1 [panel] Write a failing matcher table test (≥ 10 rows). It covers static images (skipped), `/api/**` images (gated), uppercase extensions, query strings, trailing slash, bare `/api`, and the public webhook route unchanged (D-22)
  - [ ] 4.2 [panel] Change the `proxy.ts` matcher so the image-extension skip never applies under `/api/`. Export the pattern for the test (D-22)
  - [ ] 4.3 [repo root] Add two release-gate assertions (unauthenticated `…/field-guide/<sha>/index.html` and `…/a.webp` → 401). Mark them pending with a pointer to S-223 until that story lands (D-30)
  - [ ] 4.4 [panel] Dry-run the release gate against a local server
  - [ ] 4.5 Verify Acceptance Criterion: `/api/**` is never skipped; static assets still are
  - [ ] 4.6 Verify Acceptance Criterion: path-table test passes
  - [ ] 4.7 Verify Acceptance Criterion: gate assertions present (pending until S-223)
  - [ ] 4.8 AC-to-test mapping: AC1–AC2 → `proxy.matcher.test.ts`; AC3 → release-gate script
  - [ ] 4.9 Run Tests: `pnpm run test:unit`, `pnpm run validate`

- [ ] 5.0 Implement Story S-223 - https://github.com/llipe/dev-tasks-agent-fleet/issues/517: Field-guide route with sandbox CSP
  - [ ] 5.1 [panel] Write failing L1 tests (D-23):
    - path normaliser: `..`, `%2e%2e`, `..%2f`, double-encoded, `\`, NUL, absolute, empty segments;
    - CSP builder snapshot;
    - extension map, including uppercase
  - [ ] 5.2 [panel] Write failing L2 route tests with a fake reader and session (D-22, D-23):
    - every status in spec §6.1, in order;
    - the D-23 headers on the 200 and on every error;
    - traversal makes no reader call;
    - file exactly 5 MB;
    - nested pages
  - [ ] 5.3 [panel] Implement `lib/knowledge/path.ts`, `csp.ts`, `content-type.ts`
  - [ ] 5.4 [panel] Implement the route with inline `dynamic = "force-dynamic"`. Re-check `getClaims()` (5 s fail-closed, ADR-008), validate the UUID and non-archived repository, the SHA format, path, extension and size, then call `readArtifact()` with a 5 MB cap (D-22, D-25)
  - [ ] 5.5 [panel] Apply the D-23 headers on every response. Error bodies are `FG_*` codes only (D-23)
  - [ ] 5.6 [repo root] Switch the S-222 release-gate assertions from pending to active
  - [ ] 5.7 Verify Acceptance Criterion: check order and statuses (FR-11)
  - [ ] 5.8 Verify Acceptance Criterion: exact header set on all responses (FR-12)
  - [ ] 5.9 Verify Acceptance Criterion: content type from the allowlist
  - [ ] 5.10 Verify Acceptance Criterion: error bodies carry no upstream body, token, ARN or installation id
  - [ ] 5.11 Verify Acceptance Criterion: inline route-segment config
  - [ ] 5.12 AC-to-test mapping: AC1 → T-223-01…12; AC2 → T-223-13; AC3–AC5 → T-223-14…16
  - [ ] 5.13 Run Tests: `pnpm run test:unit`, `pnpm run validate`

- [ ] 6.0 Implement Story S-224 - https://github.com/llipe/dev-tasks-agent-fleet/issues/518: Graph route and graph.json validation
  - [ ] 6.1 [panel] Add fixtures: the D-18 sample trimmed to 200 nodes (valid), `schema_version: 2`, a node without `community`, extra fields, empty `nodes`, and links to missing nodes (D-18)
  - [ ] 6.2 [panel] Write failing schema tests and L2 route tests for each envelope (`GRAPH_NOT_PRESENT`, `GRAPH_TOO_LARGE` with bytes, `GRAPH_UNSUPPORTED {found, supported}`, `GRAPH_MALFORMED {path}`, `GRAPH_UPSTREAM`, success) (D-08, D-20)
  - [ ] 6.3 [panel] Write `lib/schema/graph-v1.schema.json` per spec §5.1 (Ajv, unknown fields allowed) (D-18)
  - [ ] 6.4 [panel] Implement `lib/knowledge/graph.ts` and the route: same session/id/SHA checks as S-223; `graph.json` ≤ 15 MB; optional `GRAPH_REPORT.md` ≤ 1 MB; compression on; `Cache-Control: private, max-age=300` (D-20, D-25)
  - [ ] 6.5 Verify Acceptance Criterion: shared checks
  - [ ] 6.6 Verify Acceptance Criterion: caps and the too-large envelope
  - [ ] 6.7 Verify Acceptance Criterion: version and shape validation (FR-17, AC-8)
  - [ ] 6.8 Verify Acceptance Criterion: success envelope; extra fields accepted
  - [ ] 6.9 Verify Acceptance Criterion: compression and cache header
  - [ ] 6.10 AC-to-test mapping: AC1–AC5 → `graph-route.test.ts`, `graph-schema.test.ts`
  - [ ] 6.11 Run Tests: `pnpm run test:unit`, `pnpm run validate`

- [ ] 7.0 Implement Story S-225 - https://github.com/llipe/dev-tasks-agent-fleet/issues/519: Repository page, tabs, agent activity
  - [ ] 7.1 [panel] Write failing jsdom tests (D-28):
    - `Tabs`: arrow keys, `aria-selected`, Home/End;
    - `ArtifactState`: all five variants, `not-present` naming the path;
    - `RepositoryTable`: the name is a link;
    - `Sidebar`: active on `/repositories/*`
  - [ ] 7.2 [panel] Write failing page tests with fake queries: non-UUID, unknown and archived ids → 404; `?tab` fallback to `guide`; a repository with zero runs shows an empty state (D-28)
  - [ ] 7.3 [panel] Extract `components/Tabs.tsx` from the `CadencePicker` tablist pattern. State lives in `?tab=guide|graph|activity` (D-28)
  - [ ] 7.4 [panel] Build `components/ArtifactState.tsx` with variants `not-present`, `too-large`, `unsupported`, `malformed`, `error` (Retry) (FR-10)
  - [ ] 7.5 [panel] Build `app/(panel)/repositories/[id]/page.tsx` (D-05, D-28):
    - inline `force-dynamic`;
    - breadcrumb;
    - server-side `resolveHead` and `staleness` in parallel;
    - Field guide and Graph tabs render a placeholder `ArtifactState` until Wave C
  - [ ] 7.6 [panel] Agent activity: `getFilteredRuns({repositoryId})` with `RunHistoryRow` and `showAgentColumn`, plus the "Workflow telemetry — not yet collected" card (D-05, D-28)
  - [ ] 7.7 [panel] Make the `RepositoryTable` name a link. The Sidebar Repositories item is active by prefix (D-28)
  - [ ] 7.8 [repo root] DESIGN.md: add `Tabs`, `ArtifactState` (dark tokens only) and the repository page layout section (D-21)
  - [ ] 7.9 Manual check: navigate from Repositories to a repository, switch tabs, and reload to keep the tab. At 390 px the tabs scroll inside their container and the page doesn't scroll sideways
  - [ ] 7.10 Verify Acceptance Criterion: row link and sidebar (FR-1)
  - [ ] 7.11 Verify Acceptance Criterion: 404 cases
  - [ ] 7.12 Verify Acceptance Criterion: tabs and URL state (FR-2)
  - [ ] 7.13 Verify Acceptance Criterion: Agent activity lists only that repository's runs (FR-3, AC-1)
  - [ ] 7.14 Verify Acceptance Criterion: telemetry placeholder (FR-4)
  - [ ] 7.15 Verify Acceptance Criterion: `ArtifactState` variants (FR-10)
  - [ ] 7.16 Verify Acceptance Criterion: placeholder states on Field guide and Graph
  - [ ] 7.17 Verify Acceptance Criterion: breadcrumb; inline route config
  - [ ] 7.18 AC-to-test mapping: AC1–AC8 → component and page tests; PRD AC-1 end-to-end in S-229 (Wave C)
  - [ ] 7.19 Run Tests: `pnpm run test:unit`, `pnpm run validate`

## Decisions Consumed

| ID   | Decision (short form)                                                                           |
| ---- | ----------------------------------------------------------------------------------------------- |
| D-05 | Three tabs; Agent activity reuses `runs`; workflow telemetry is a separate PRD                  |
| D-06 | Repository-owned artifacts read live from GitHub; SHA-keyed cache                               |
| D-08 | Native viewer over `graph.json`; schema-version guard                                           |
| D-11 | Advisory staleness: >30 days or >100 commits                                                     |
| D-14 | Reuse the fleet App; down-scoped tokens; IAM via infra pass                                     |
| D-18 | graphify 0.9.120 output measured                                                                |
| D-19 | Panel constraints from research (role, matcher, no CSP, stale comment)                          |
| D-20 | 15 MB graph cap; tests excluded                                                                 |
| D-21 | Dark-only tokens                                                                                |
| D-22 | Matcher never skips `/api/**`; routes re-check the session                                      |
| D-23 | Per-response CSP with `sandbox`; extension allowlist; security headers                          |
| D-24 | Server-only, single-repository, read-only token; fail closed on broader grants                  |
| D-25 | SHA-pinned route; HEAD 60 s; 64 MB LRU; raw contents; 5 MB guide-file cap                       |
| D-28 | UI conventions: `?tab=`, `Tabs`, 404s, row link, sidebar prefix, `getFilteredRuns`              |
| D-29 | Testing layers; injected fetch and fake Secrets Manager                                         |
| D-30 | Infra first, no flag, release-gate assertions                                                   |
