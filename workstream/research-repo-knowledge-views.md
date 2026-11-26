# Research — Repository Knowledge Views (HOW phase)

## Changelog

| Version | Date       | Summary                                                                                   | Author     |
| ------- | ---------- | ----------------------------------------------------------------------------------------- | ---------- |
| 1.0     | 2026-11-26 | Initial bounded codebase research for `docs/requirements/prd-repo-knowledge-views.md` (slices S1-S8, eight questions from the brief). | researcher |

## Provenance

- **Repository:** `/home/user/dev-tasks-agent-fleet` (local checkout; remote name not verified)
- **Branch at research time:** `claude/happy-mccarthy-xqdrco`. Default branch not determined in this run.
- **Commit SHA:** `534ed372f0333162acb9eaf8a3e27517fc3a66e0`. Consumers must treat this artifact as stale when HEAD advances past this SHA.
- **Invoking agent:** not stated in the brief. Inferred to be `product-engineer` (HOW phase, pre-spec).
- **Research question:** Ground the HOW phase of the Repository Knowledge Views PRD (panel credentials, GitHub App key, repositories and runs data, routing and UI, proxy gate, caching and HTTP clients, test conventions, DESIGN.md) with file:line evidence.
- **Date:** 2026-11-26
- **Cap accounting:** the PRD and the decision log are inputs and are not counted toward the 30-file cap. The 30 cited files are the file map below.
- **Method:** read-only. No AWS, Supabase, GitHub or Fly calls were made. Live state is not asserted.
- **Package attribution:** the canonical `tech.md` foundation doc is absent; the legacy `technical-guidelines.md` name is present (foundation-document fallback rule). Package list taken from the workspace manifest: `panel` and the `agentcore/cdk` package of `dependency-update`. Python agent packages (`agents/bug-fix`, `agents/code-review`, `agents/dependency-update`, `agents/security-analyst`) sit outside the pnpm workspace and are attributed by directory name. `infra/`, `supabase/`, `TESTING.md` and `DESIGN.md` are attributed `(repo root)`.

## Answer first

1. The panel holds **no GitHub credential and makes no GitHub API call today**. Its only AWS identity is the Fly OIDC → STS role `panel-agentcore-invoke`, whose committed inline policy grants only `bedrock-agentcore:InvokeAgentRuntime`. The App private key is in Secrets Manager; its ARN is per row in `github_installations.private_key_secret_arn`.
2. The agents mint installation tokens in Python (RS256 JWT → `POST /app/installations/{id}/access_tokens`). **No request body is sent, so no `permissions` down-scope exists anywhere.** There is no shared TypeScript token code.
3. `repositories` and `runs` have the columns needed. `runs` can already be filtered by `repository_id` through `getFilteredRuns` and `getRunStatusCounts`. `getRepositoryById` exists.
4. **Gate gap:** the `proxy.ts` matcher excludes paths ending in lowercase `.svg/.png/.jpg/.jpeg/.gif/.webp/.ico` from the auth gate on every route, including `/api/**`. Field-guide image assets with those extensions would not pass through the gate.
5. No security headers or CSP exist anywhere in the panel. No cache exists beyond the module-level AWS credential cache. No graph or canvas library and no light-theme tokens exist.
6. The `/repositories/[id]` route needs three existing-code changes: the row name is not a link, the sidebar active check is an exact match, and no tabs component exists (a `tablist` pattern exists in `CadencePicker`).
7. Test infrastructure is Vitest (`unit`, `component`, `integration`) plus Playwright E2E against a real local Supabase stack with AgentCore stubbed at HTTP. **No GitHub test double exists in the panel.**

## Relevance-ranked file map

Each entry is attributed to its package. Line numbers refer to the commit above.

1. `panel` — `panel/lib/aws/credentials.ts:168-170` (`AGENT_RUNTIME_ROLE_ARN` read), `:185-189` (RoleSessionName, DurationSeconds 900), `:233-258` (single provider, cache, `credentialSource`)
2. `(repo root)` — `infra/trust-policy.json:5-9` (Federated `oidc.fly.io/felipe-mallea`, `aud` = `sts.amazonaws.com`, `sub` like `felipe-mallea:dt-agent-fleet-panel:*`)
3. `(repo root)` — `infra/agentcore-invoke-policy.json:14-29` (InvokeAgentRuntime on two runtimes, each with `/runtime-endpoint/DEFAULT`)
4. `(repo root)` — `infra/environments.yaml:14-16,21-29,45,51` (account, runtimes, `secrets_prefix: agent-fleet/prod/`, stale OIDC comment at :51)
5. `(repo root)` — `infra/changes/20261014-fly-oidc-issuer-trust/plan.md:1-8` (header: ChangeId, issue #280, environment, identity, cost, approval) and Discovery/Steps sections
6. `(repo root)` — `infra/changes/20261014-fly-oidc-issuer-trust/commands.sh` (append-only command log; step-by-step approval timestamps in comments; `put-role-policy … invoke-runtime`)
7. `(repo root)` — `infra/changes/20261014-fly-oidc-issuer-trust/result.md` (step table; trailing `status: verified`)
8. `(repo root)` — `infra/changes/20261023-bug-fix-runtime/role-policy.json:71-82` (`ReadFourSecrets`; `GITHUB_APP_PRIVATE_KEY-t4sXT2` at :77)
9. `bug-fix` — `agents/bug-fix/app/bugFix/credentials.py:166-186` (PostgREST read of `github_installations`), `:226-243` (`_fetch_pem`), `:284-336` (`mint_installation`), `:372-393` (`resolve_github_session`), `:395-413` (`refresh_if_stale`), `:105-107` (`is_stale`)
10. `(repo root)` — `supabase/migrations/20260902200101_initial_schema.sql:38-47` (`github_installations`), `:56-68` (`repositories`), `:112` (`runs.repository_id`), `:150` (`idx_runs_repo`), `:234-251` (`v_runs`)
11. `panel` — `panel/lib/supabase/queries.ts:64-73` (`getEnabledRepositories`), `:81-87` (`getRepositoryById`), `:372-390` (`getAllRunsByAgentSlug`), `:425-441` (shared run filter, `repositoryId` at :434-436), `:465-492` (`getFilteredRuns`), `:509` (`getRunStatusCounts`), `:729-742` (`getSingleInstallation`), `:748-758` (`getRepositories`)
12. `panel` — `panel/lib/supabase/types.ts:58-68` (`GithubInstallationRow`), `:71-82` (`RepositoryRow`), `:84-` (`v_runs` note)
13. `panel` — `panel/lib/domain/run-filter.ts:41-52` (`RunFilter`, `repositoryId`), `:83` (`repo` URL param)
14. `panel` — `panel/app/(panel)/layout.tsx:36-43` (server-side auth check, fail-closed), `:66-76` (`AppShell` + bell)
15. `panel` — `panel/app/(panel)/repositories/page.tsx:23-25` (inline `force-dynamic`), `:27-40` (page, reads `getRepositories`)
16. `panel` — `panel/components/repositories/RepositoryTable.tsx:51-60` (empty state, `role="status"`), `:62-96` (semantic table), `:83` (name cell is plain text, not a link), `:106-` (`ArchiveAction`)
17. `panel` — `panel/components/shell/Sidebar.tsx:51-52` (`repositoriesActive` exact match), `:88-91` (Repositories nav link)
18. `panel` — `panel/components/runs/RunHistoryRow.tsx:37-44` (`showAgentColumn`, default false), `:76-88` (repository cell), `:95-101` (row link via chevron cell)
19. `panel` — `panel/app/(panel)/runs/page.tsx:162` (`showAgentColumn` set for cross-agent feed); shares `getFilteredRuns` with the agent run-history screen
20. `panel` — `panel/app/(panel)/webhooks/[id]/page.tsx:41-49` (UUID guard then `notFound()`; the nearest precedent for a detail route)
21. `panel` — `panel/components/schedules/CadencePicker.tsx:79-85` (`role="tablist"`, `role="tab"`, `aria-selected`)
22. `panel` — `panel/proxy.ts:1-10` (Node runtime), `:60` (5 s `getClaims` bound), `:146-152` (gate entry, public and internal short-circuits), `:170` (`getClaims`), `:172-175` (401 JSON for `api`, 302 for `ui`), `:199-202` (matcher)
23. `panel` — `panel/lib/auth/route-policy.ts:30-77` (`classifyRoute`; `/api/**` → `api` at :71-73; `/api/internal/**` and `/api/webhooks/**` → `internal` at :56-67)
24. `panel` — `panel/next.config.ts:9-16` (no `headers()`; `output: "standalone"` at :15)
25. `panel` — `panel/playwright.config.ts:8-10` (AgentCore stub), `:46-66` (single worker, `retries: 0`), `:58` (`globalSetup`), `:70-71` (auth setup project)
26. `panel` — `panel/vitest.config.ts:5-8` (project mapping), `:26-70` (`unit`, `component` jsdom with `setupFiles`, `integration` single fork)
27. `panel` — `panel/tests/unit/credentials.test.ts:22-48` (mocks of `node:fs`, `node:http`, STS, credential providers)
28. `(repo root)` — `TESTING.md:58-66` (layer table), `:72` (Layer 2.5 must not mock the data layer), `:247-` (fixtures and mocking)
29. `(repo root)` — `DESIGN.md:53-60` (core colours), `:91-100` (status tokens), `:103-110` (utility aliases), `:301-` (§3.7 KLabel), `:534-547` (§5.6 Repositories), `:598` (§5.7 empty-state panel), `:746` (§5.9 empty state), `:1065` (§11.1 CSS architecture)
30. `panel` — `panel/styles/tokens.css:18-22` (core), `:25-33` (neutral ramp), `:36-44` (accent ramp), `:54-56` (`--st-*`), `:59-61` (`--rule`, `--muted`, `--faint`). No light-theme block in this file.

Not cited in this map: the other three agent `credentials.py` files (`agents/{dependency-update,security-analyst,code-review}/app/*/credentials.py`). They share the mint function shape (`mint_installation` at :152-170, same request, no body; `jwt.encode` RS256 at :159-163). Confirmed by grep, not read line by line.

## Slice findings

### S1 — Components and modules (AWS credentials, Fly OIDC, IAM)

- **Credential branches.** `panel` — `panel/lib/aws/credentials.ts:36-38`: "on Fly" means `FLY_APP_NAME` is set and the Machine OIDC socket `/.fly/api` exists. Otherwise the SDK's `fromNodeProviderChain()` runs (`:71`). `credentialSource()` returns `fly-oidc` or `local-chain` (`:258-260`).
- **Fly branch.** `fetchFlyOidcToken` posts `{aud:"sts.amazonaws.com"}` to `/v1/tokens/oidc` over the Unix socket (`:119-150`). `extractOidcToken` accepts a raw JWT body (`:84-117`). `assumeRoleFromFly` (`:167-216`) reads `AGENT_RUNTIME_ROLE_ARN` (`:168-170`; missing → `CredentialsUnavailableError`) and calls `AssumeRoleWithWebIdentity` with `DurationSeconds: 900` (`:189`).
- **Caching.** Module-level `cached` and `inFlight` (`:245-256`). Refresh happens `REFRESH_MARGIN_MS` (60 s, :33) before expiry, with single-flight. No Secrets Manager client exists in `panel/lib/aws/` today.
- **Role.** The role is `panel-agentcore-invoke` in account `755641879575` (`infra/changes/20261014-fly-oidc-issuer-trust/plan.md`, Discovery section). Its trust is `infra/trust-policy.json:5-9`. Its only committed inline policy is `invoke-runtime` = `infra/agentcore-invoke-policy.json`, which lists two runtimes, `dependency-update` and `security-analyst`, each with its `/runtime-endpoint/DEFAULT` ARN (:20-27). The `bug-fix` and `code-review` runtimes are absent from this file. Live state was not checked.
- **Secrets grant today.** None in the panel role. `secretsmanager:GetSecretValue` exists only on the agent runtime role in `infra/changes/20261023-bug-fix-runtime/role-policy.json:71-82`, which names `agent-fleet/prod/GITHUB_APP_PRIVATE_KEY-t4sXT2` (:77).
- **Infra record structure (most recent panel-IAM change).** `infra/changes/20261014-fly-oidc-issuer-trust/` contains `plan.md`, `commands.sh`, `result.md`, `rollback.sh` and `backup/` (before-state JSON). `plan.md` header fields: ChangeId, Issue, Environment, Resolved identity, Cost, Approval status (:1-8). It then has a Discovery section, a Backup section, and per-step blocks with Kind, Tool, Touches state, Forward, Verify and Revert. `commands.sh` is an append-only log with an approval timestamp per step. `result.md` is a table of Step, Status, Backup id, Restore command, Verified at, Evidence, ending in `status: verified`. The later record `20261015-retire-fly-oidc-personal` (not opened in detail) deletes the unused `oidc.fly.io/personal` provider; its header states "No IAM role trust policy references it."
- **Stale comment.** `infra/environments.yaml:51` says the trust is `sub personal:dt-agent-fleet-panel:*`. `infra/trust-policy.json:9` says `felipe-mallea:dt-agent-fleet-panel:*`. The JSON matches the 2026-10-14 change record. The YAML comment is stale.

### S2 — APIs and contracts (GitHub App key and token minting)

- **Where the key ARN lives.** `github_installations.private_key_secret_arn text` (nullable), `supabase/migrations/20260902200101_initial_schema.sql:43`. Other columns: `id uuid`, `github_org_slug text unique`, `installation_id bigint unique` (GitHub's numeric id), `app_id bigint`, `is_enabled boolean` (:38-47). The agent reads them with a PostgREST `select=app_id,installation_id,private_key_secret_arn` call (`agents/bug-fix/app/bugFix/credentials.py:173-176`). The lookup is `github_org_slug`-scoped (:166-186).
- **Key read.** `_fetch_pem(secret_arn)` calls `secretsmanager.get_secret_value` and reads `SecretString` (`credentials.py:226-243`). Failures are typed `PEM_UNAVAILABLE`, and the value is not logged.
- **Token mint.** `mint_installation` (`credentials.py:284-336`):
  - RS256 JWT with `iat = now-60`, `exp = now+540`, `iss = app_id` (:287-296).
  - `requests.post` to `https://api.github.com/app/installations/{installation_id}/access_tokens`, with `Authorization: Bearer` and `Accept` headers, `timeout=30`, `allow_redirects=False` (:298-307).
  - **No `json=`, `data=` or `permissions` body is sent** (:298-307). The response `permissions` is read back (:335), and `has_issues_write` gates it (:274-276, :405-406).
- **Staleness.** `is_stale` is 45 minutes (`credentials.py:105-107`, `TOKEN_STALE_THRESHOLD_MINUTES`). `refresh_if_stale` re-mints (:395-413).
- **Shared TypeScript code.** None. The panel has no `api.github.com` reference, no octokit and no JWT signing. `GithubInstallationRow` is a type only (`panel/lib/supabase/types.ts:58-68`).
- **App id and installation id.** Stored in `github_installations.app_id` and `.installation_id` (bigint). `repositories.installation_id` is a different thing: a `uuid` FK to `github_installations.id` (`initial_schema.sql:58`). The name collision is a known trap.
- **Panel read of the installation.** `getSingleInstallation` (`panel/lib/supabase/queries.ts:729-742`) reads the first row and throws if none exists.

### S3 — UI surfaces (repositories and runs)

- **Repositories table.** `repositories` columns (`initial_schema.sql:56-68`): `id uuid`, `installation_id uuid` (FK, cascade), `github_repo_id bigint` (nullable), `full_name text` (unique per installation), `default_branch text` (default `main`), `is_enabled boolean`, `metadata jsonb`, `archived_at timestamptz`, `created_at`, `updated_at`. There is no owner/name split, no commit SHA cache and no GitHub node id.
- **Queries.** `getEnabledRepositories` (`queries.ts:64-73`), `getRepositoryById` (:81-87, returns archived rows too, so the caller must check `archived_at` and `is_enabled`), `getRepositories` (:748-758, excludes archived by default).
- **Runs by repository.** `runs.repository_id uuid` is nullable with `on delete set null` (`initial_schema.sql:112`). Index `idx_runs_repo (repository_id, created_at desc)` exists (:150). `v_runs` is `runs.*` plus `agent_slug`, `agent_name`, `repository_full_name` and `effective_status` (:234-251). The panel reads runs only through `v_runs`.
- **Filtering by repository.** `getFilteredRuns` and `getRunStatusCounts` accept `repositoryId` through the shared `applyRunFilterClauses` (`queries.ts:425-441`, `:434-436`). `getRunsByAgentSlug` (:90) and `getAllRunsByAgentSlug` (:372) filter by agent only. No `getRunsByRepositoryId` exists. The URL param is `repo` (`run-filter.ts:83`).
- **Row component.** `RunHistoryRow` (`panel/components/runs/RunHistoryRow.tsx`). Props are `row` and `showAgentColumn` (default false, :37-44). The row is a semantic `<tr>`. The whole-row link is the chevron cell `Link` to `/runs/{id}` (:95-101). The `/runs` page passes `showAgentColumn` (`runs/page.tsx:162`). A repository-scoped Agent activity tab would need the same choice made explicitly.
- **Repository row.** `RepositoryTable` renders `row.full_name` as plain text (`RepositoryTable.tsx:83`). Per row it renders an Archive button and dialog (:90-92, `ArchiveAction` :106-). The row is not a link.
- **Sidebar.** Nav items are in `Sidebar.tsx:75-117`. `repositoriesActive` is `pathname === "/repositories"` (:51-52), so `/repositories/[id]` would not highlight the item without a change.
- **Route tree.** `app/(panel)/` contains `page.tsx`, `agents/[slug]`, `runs/[id]`, `repositories`, `schedules`, `webhooks/[id]`, `notifications`, `dev/`. No `repositories/[id]` exists.
- **Layout.** `app/(panel)/layout.tsx` runs `supabase.auth.getClaims()` server-side (:36-43) and renders `AppShell` with `NotificationBell` (:66-76). Pages inherit it.

### S4 — Tests (see also S7)

- Vitest projects are defined in `panel/vitest.config.ts:26-70`: `unit` (node, `tests/unit/**` and `tests/smoke.test.ts`), `component` (jsdom, `tests/component/**`, `tests/setup.ts`), and `integration` (node, `tests/integration/**`, `pool: forks, singleFork: true`, :59-64).
- Test-only alias neutralises `server-only` (`vitest.config.ts:13-18`).
- No panel test exercises a repository page, a GitHub call, or a graph. The one page-wiring example is `tests/component/repositories-page-wiring.test.tsx` (mocks `@/lib/supabase/queries` and the actions module, :23-34).

### S5 — Data model

- Covered in S3 above. Summary of gaps versus PRD requirements: no per-repository artifact cache (FR-9 has no table, and the PRD says not to copy artifacts into Supabase, FR-6); no per-repository staleness fields; `archived_at` exists (FR-1 applies to non-archived).
- Migration history includes scheduler, webhook and notification tables with `repository_id` FKs (scheduler and webhook migrations; grep only). No migration touches `repositories` after the initial schema (grep over `supabase/migrations`).

### S6 — Config, env and CI

- Panel env: `AGENT_RUNTIME_ROLE_ARN` (secret), `AWS_REGION` (non-secret, set in the Fly config; not opened here), `FLY_APP_NAME`, `FLY_MACHINE_ID` (`credentials.ts:19`, `:36`, `:185`).
- `output: "standalone"` (`panel/next.config.ts:15`). No `headers()` or `async headers` (:9-16).
- panel package manifest scripts: `lint`, `format:check`, `typecheck`, `test` (`vitest run`), `test:unit`, `test:integration`, `test:e2e` (`playwright test`), `audit` (`node scripts/audit.mjs`), `validate`. These are the canonical names.
- No CSP, `X-Frame-Options`, `nosniff` or `Referrer-Policy` string exists in `panel/app`, `panel/lib`, `panel/next.config.ts` or `panel/proxy.ts` (grep). The only `headers` uses are request-header reads (`webhooks/page.tsx`, `webhooks/[id]/page.tsx`) and a 302 `Location` in `api/auth/logout`.
- Playwright CI and the Docker-gated Layer 2.5 suites are described in `TESTING.md` (CI-vs-local section, :77-99). Not opened in detail.

### S7 — Relationships and integration seams

- **Credential chain.** Fly OIDC socket → `AssumeRoleWithWebIdentity` (role `panel-agentcore-invoke`) → AgentCore invoke (the invoke wrapper beside it; not opened). Secrets Manager is not in this chain today.
- **Agent key chain.** Agent runtime role (`agent-fleet-bug-fix-runtime`, per `agents/bug-fix` change records) → `github_installations` row → Secrets Manager PEM → JWT → installation token. The panel would be a second reader of the same secret. The PRD (D-14) accepts that the panel role can read a write-capable key.
- **Proxy ↔ routes.** `proxy.ts` gates pages (302) and `/api/**` (401 JSON). Route policy `classifyRoute` (`route-policy.ts:71-73`) means `/api/repositories/**` would be `api` class. That gives 401 JSON, not a redirect, for an iframe `GET`.
- **Test seams.** Existing unit mocks at module boundaries (`credentials.test.ts:22-48`). E2E runs against real local Supabase with AgentCore stubbed through `AWS_ENDPOINT_URL_BEDROCK_AGENTCORE` (`playwright.config.ts:8-10`). Operator provisioning is in `global-setup` (`playwright.config.ts:58`). There is no GitHub stub in the panel. The Python siblings have `tests/component/fake_github.py` (per `TESTING.md` Packages table).

### S8 — Prior history

- Change records for panel OIDC: `20261014-fly-oidc-issuer-trust` (issue #280; D-07 raw-JWT shape; D-08/D-09 referenced) and `20261015-retire-fly-oidc-personal` (follow-up).
- `panel/lib/aws/credentials.ts:60-64` records that the Fly socket returns a raw JWT as of 2026-10-14 (verified live then).
- The decision log (D-13) corrects D-06: the panel makes no GitHub API calls and holds no installation token today.
- `/DESIGN.md` §5.6 records that the Repositories screen is a first-pass layout (:534-536), not a `ux-engineer` pass.

## Relationships

- `RepositoryTable` ← `app/(panel)/repositories/page.tsx` ← `getRepositories` (`queries.ts:748`). A `/repositories/[id]` page would reuse `getRepositoryById` (:81) and `getFilteredRuns` (:465).
- Agent activity tab → `getFilteredRuns` (with `repositoryId`, `agentSlug: null`) → `RunHistoryRow` with `showAgentColumn` set by choice (`runs/page.tsx:162` is the precedent for `true`).
- Field-guide route → `proxy.ts` gate (`:146-175`) → artifact fetch (no existing GitHub client) → `CSP` header (none exists).
- Graph tab → `graph.json` fetch → viewer (no graph library in the panel dependency list).
- Infra pass → `infra/agentcore-invoke-policy.json` and/or a new policy → change record under `infra/changes/<date>-<slug>/` → `infra/environments.yaml` runtime or secret references.

## Risks and gotchas

1. **Matcher bypass for asset extensions.** `panel/proxy.ts:201` excludes `.svg|.png|.jpg|.jpeg|.gif|.webp|.ico` on all routes, including `/api/**`. Verified by evaluating the matcher regex: `/api/repositories/x/field-guide/img/arch.svg` is not gated; `.PNG` (upper case) is gated, since the regex is case-sensitive. Field-guide assets with these extensions would be served without the session check unless a handler enforces it.
2. **No down-scope exists.** The mint request has no `permissions` body (`credentials.py:298-307`). FR-7's `contents:read, metadata:read` has no precedent in code. Whether GitHub grants the installation's full permissions without it is not verified in this run (no external source consulted).
3. **Read-only mint is not enforced in the panel.** Nothing in `panel/` enforces the read-only property. D-14 states it as an accepted trade-off.
4. **Two `installation_id` meanings.** `repositories.installation_id` (uuid FK) vs `github_installations.installation_id` (bigint, GitHub's id). Confusion is likely in joins and in the token-mint call.
5. **Archived repositories.** `getRepositoryById` returns archived rows (`queries.ts:81-87`). FR-1 requires non-archived.
6. **Stale OIDC comment.** `infra/environments.yaml:51` (personal) vs `infra/trust-policy.json:9` (felipe-mallea).
7. **Invoke policy file incomplete.** `infra/agentcore-invoke-policy.json` lists two runtimes. The `bug-fix` change record (20261023) shows a separate role. Whether the live `panel-agentcore-invoke` policy matches the file is not verified.
8. **Sidebar exact match.** `Sidebar.tsx:51-52`.
9. **Row not linkable.** `RepositoryTable.tsx:83`. The Archive action is inside the same row.
10. **Light theme absent.** No light tokens in `panel/styles/tokens.css` (grep for `light`, `prefers-color-scheme`, `data-theme` returned nothing) and none in `DESIGN.md`. FR-21 requires light/dark.
11. **No graph/canvas section.** `DESIGN.md` has no graph, canvas, node or edge section (grep). Status colours are `--st-ok`, `--st-fail`, `--st-timeout` and an accent for running.
12. **Caching precedent.** The only server-side in-memory caches are the AWS credential cache (`credentials.ts:68-69`) and an ajv validator map (not in the file map). Every data page sets `dynamic = "force-dynamic"` with `revalidate = 0` (`repositories/page.tsx:23-25`). FR-9's SHA-keyed cache has no precedent.
13. **Single-process cache.** An in-memory cache is per process. Whether the Fly app runs a single Machine was not checked.
14. **Foundation-document naming.** The canonical `tech.md` is absent; the legacy name is the fallback. `dev-tasks migrate docs` should be proposed, per the CLAUDE.md rule.

## External sources (optional)

None consulted. All findings are codebase-first. GitHub API behaviour (permission down-scoping, token lifetime) is not asserted here.

## Not investigated

- Live AWS state (IAM role policies, trust, Secrets Manager secret names and ARNs). No calls were made.
- Live database contents: `github_installations` rows and `private_key_secret_arn` values.
- Live Fly configuration (`fly secrets`, Machine count, `FLY_APP_NAME`).
- The three other agents' `credentials.py` files beyond grep.
- The other AWS wrapper modules, the Supabase auth modules, the schema validator, and the integration and E2E suites beyond their configs. Omitted to keep the cited-file count at 30.
- The panel Dockerfile, the Fly config and the scripts directory.
- The panel deployment runbook (referenced by change record 20261015).
- The `repo-knowledge` skill, `graph.yml` and the riel field guide (other repositories; out of scope for this run).
- graphify output format (`graph.json`, `schema_version`). PRD D-01 states it; not verified against the tool.
- The graph library choice and its licence.
- `/DESIGN.md` §9 (responsive), §10 (icons), §11.2-11.3 and §12 in detail.

## Confidence

- **High:** code facts in the file map, including the matcher regex result (evaluated), the absence of `permissions` in the mint request, the absence of headers and CSP, the absence of GitHub calls in `panel/`, and the table and column definitions.
- **Medium:** AWS role contents (repo copy only), and the claim that the `bug-fix` runtime role is separate (from change records, not live).
- **Low / not verified:** live Secrets Manager ARNs, live DB rows, GitHub permission behaviour, and whether the Fly app is a single Machine.

## Implications for the spec

These are facts the spec must resolve. They are not recommendations.

1. **Asset gating.** The spec must state how files under `/api/repositories/[id]/field-guide/**` with `.svg/.png/.jpg/.jpeg/.gif/.webp/.ico` extensions meet the authenticated-route requirement (FR-11), given the matcher exclusion at `proxy.ts:201`.
2. **Security headers.** No CSP or security-header mechanism exists to extend. The spec must name the mechanism that sets FR-12 headers and state whether it covers the 401 and error responses.
3. **Token scope.** The spec must define the `permissions` request body for the installation-token call (FR-7), because no code sends one today. It must also define what the panel does when the response grants more than `contents: read` and `metadata: read`.
4. **Key ARN source.** The spec must decide whether the panel reads `github_installations.private_key_secret_arn` at runtime (as the agents do) or whether the ARN is named in the IAM statement. The current repo copy of the role policy names no App-key ARN.
5. **Infra change record.** FR-7's IAM work will need a new `infra/changes/<date>-<slug>/` record, following the 20261014 structure (plan, commands, result, rollback, backup). `infra/agentcore-invoke-policy.json` and `infra/environments.yaml` must stay consistent with the live role.
6. **Stale comments.** `infra/environments.yaml:51` must not be copied into the spec as the trust subject. The spec should cite `infra/trust-policy.json:9`.
7. **Tab state.** The URL-addressable tab requirement (FR-2) can follow the existing query-string precedent (`run-filter.ts` says filter state lives in the URL). The spec must state the tab parameter. No tabs component exists. `CadencePicker` has a `tablist` pattern (:79-85).
8. **Agent activity tab.** The spec must state whether `showAgentColumn` is on (`RunHistoryRow.tsx:37-44`), and must reuse `getFilteredRuns` with `repositoryId` (`queries.ts:434-436`), not a new query. No new telemetry (FR-3).
9. **Row link and sidebar.** The spec must state that the repository name becomes a link (`RepositoryTable.tsx:83`), and that the Repositories nav item is active for `/repositories/[id]` (`Sidebar.tsx:51-52` is an exact match today).
10. **Not-found and archived.** The spec must state the behaviour for an unknown id (UUID guard then `notFound()`, precedent `webhooks/[id]/page.tsx:41-49`), and for an archived repository (`getRepositoryById` returns it).
11. **Light theme.** FR-21 requires light and dark. No light tokens exist (`panel/styles/tokens.css`, `DESIGN.md`). The spec must name where light values come from, and `DESIGN.md` must be updated when the UI contract changes (CLAUDE.md rule).
12. **Graph viewer.** No graph or canvas library is in the panel dependency list and no DESIGN.md section covers it. FR-16 to FR-21 require a pinned library and a DESIGN.md section. The choice is open.
13. **Cache.** FR-9's SHA-keyed cache has no precedent. The spec must state the store (process memory vs other), the eviction rule and the behaviour across process restarts.
14. **Test seams.** The panel has no GitHub test double. TESTING.md has no panel GitHub convention. The spec must state the Layer 1/2/2.5 split for the GitHub client and the artifact route. `TESTING.md:72` forbids Layer 2.5 from mocking the data layer.
15. **Doc names.** The canonical `tech.md` is absent here; the legacy name is present. Any spec citing the foundation doc should use the legacy name until `dev-tasks migrate docs` runs.
