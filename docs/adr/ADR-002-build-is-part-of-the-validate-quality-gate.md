# ADR-002: `build` is part of the `validate` quality gate

## Status

Accepted — 2026-08-25

## Context

`docs/technical-guidelines.md` §12 defined the aggregate gate as:

```
validate    # aggregate quality gate: lint + format:check + typecheck + test + audit
```

`build` was deliberately absent, on the implicit reasoning that `tsc --noEmit` already
proves the code compiles.

That reasoning is wrong for this stack, and #60 demonstrated it at cost. `next build` failed
on three separate defects that a green `validate` had never surfaced:

1. **`Module not found: Can't resolve './x.js'`** — the codebase uses TypeScript ESM-style
   `.js` import specifiers. `tsc` resolves these natively; webpack only maps them onto
   `.ts`/`.tsx` via `resolve.extensionAlias`, which was not configured.
2. **`UnhandledSchemeError: Reading from "node:crypto"`** — a `"use client"` component
   imported the `@fleet/shared` barrel, which re-exports `buildSessionId` and so pulled
   `node:crypto` into the browser bundle. Type-checking has no concept of a bundle boundary,
   so this is invisible to `tsc` by construction.
3. **`Cannot find module '@tailwindcss/postcss'`** — in Tailwind v4 the PostCSS plugin is a
   separate package. A missing build-time-only dependency is not a type error.

All three are properties of _bundling_, not of _types_. The first two are structurally
undetectable by `tsc` no matter how strict the configuration. The failures surfaced during a
deploy attempt, which is the most expensive place to find them.

A fourth defect of the same family was found later in the same cycle and is **still not
caught by `build`**: `src/lib/cost.ts` reads `pricing/pricing-v1.json` at runtime with
`readFileSync`, and the Dockerfile did not copy it into the runtime image. Next.js standalone
output traces static imports only, so a filesystem-read asset is never included
automatically. This produced `ENOENT` at request time — a successful build, a broken deploy.

## Decision

**`build` runs as part of `validate`, in both the root aggregate and every package that has
a build step.**

The root gate is now:

```
lint → format:check → typecheck → test → build → check-boundaries → audit
```

`build` is ordered after `test` so that fast feedback still comes first, and before `audit`
because `audit` currently fails on pre-existing advisories tracked in
[#58](https://github.com/llipe/dev-tasks-agent-fleet/issues/58) and would otherwise mask it.

`.github/workflows/control-plane.yml` runs the same aggregate, so the bundling defect class
is now caught in CI on the branch rather than at deploy time.

Runtime assets read from the filesystem rather than imported are **not** covered by this gate
and remain a manual review obligation: any `readFileSync` of a repo-relative path needs a
matching `COPY` in the Dockerfile. `apps/control-plane/Dockerfile` carries a comment at that
`COPY` line explaining why it cannot be inferred.

## Alternatives Considered

**Rely on `tsc --noEmit` alone.** Rejected — this was the status quo, and it missed all three
defects. Two of them are not type errors in any configuration.

**Add a separate `build` CI step outside `validate`.** Rejected: it would catch the defects
in CI but not locally, and §12 states `validate` is "what CI runs and what should pass
locally before a PR". Two divergent definitions of the gate is the drift this repo's
single-source-of-truth principle exists to prevent.

**Add an ESLint rule banning server-only imports from client components.** Not rejected —
complementary, and cheaper feedback than a full build for defect 2 specifically. `import/no-restricted-paths`
or the existing `check-boundaries` script could cover it. Deferred as a follow-up rather than
a substitute, since it addresses one of the three causes.

**Make the build produce the runtime asset manifest and assert against the image.** Deferred
as disproportionate for one pricing file. The Dockerfile comment plus this ADR is the
mitigation.

## Consequences

**Positive.** Bundling defects are caught on the branch. The local and CI definitions of the
gate stay identical. Deploy attempts stop being the discovery mechanism for webpack
configuration problems.

**Negative.** `validate` is slower — `next build` adds roughly 10–15 seconds locally, more in
CI. This is paid on every run to catch a class of defect that appears rarely, which is the
correct trade only because the alternative discovery point is a failed deploy.

**Follow-up actions.**

- Consider a lint rule enforcing the server/client import boundary, so defect 2 fails in
  seconds rather than at bundle time.
- `pnpm run audit` currently fails on 12 pre-existing advisories (#58), so the full gate is
  not green on this branch for reasons unrelated to this decision.

## Related

- Requirements: `docs/requirements/PRD-agent-control-plane-v1-en.md`
- Workstream: `workstream/tasks-issue-60-control-plane-iam.md`
- Issues: [#60](https://github.com/llipe/dev-tasks-agent-fleet/issues/60),
  [#58](https://github.com/llipe/dev-tasks-agent-fleet/issues/58)
- Code: `package.json`, `apps/control-plane/package.json`,
  `apps/control-plane/next.config.ts`, `apps/control-plane/Dockerfile`,
  `.github/workflows/control-plane.yml`, `packages/shared/package.json` (`exports`)
- Docs updated: `docs/technical-guidelines.md` §12;
  `docs/runbook-deployment.md` §14
