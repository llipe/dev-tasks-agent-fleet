# Fidelity Report — Issue #510 (bug-fix image Node patch bump)

> **Fidelity: High** · **Highest drift impact: None** · **Blocking findings: none**
>
> Scope: issue [#510](https://github.com/llipe/dev-tasks-agent-fleet/issues/510), PR #511, branch `chore/510-node-patch-bump` (one commit `fffad85` on `main` `256e9ef`), diff `origin/main...origin/chore/510-node-patch-bump`.
>
> Drift findings are **non-blocking**. They do not hold PR readiness or the issue's completion. Any that come up go to `product-engineer` (`activity-drift-reconciliation`), and code fixes go to `developer`. This audit adds to the quality gates. It does not replace them.

## Changelog

| Version | Date       | Summary                    | Author   |
| ------- | ---------- | -------------------------- | -------- |
| 1.0     | 2026-11-27 | Initial Audit Mode report. | verifier |

## Summary

The bug-fix agent's container image ships three Node.js versions, one for each supported major (22, 24 and 26). It picks one for each repository it works on. This change moves each of them to the latest bug-fix release in its line: 22.23.5, 24.22.3 and 26.13.1. Version 26 stays the default. The majors don't change, so the same repositories are accepted and refused as before. The only difference is that they now run on newer, patched Node releases.

The new release files are downloaded from nodejs.org and checked against fingerprints written into the build. This audit fetched those fingerprints from nodejs.org on its own, and all three match. The two places that list the versions agree. The tests no longer spell out specific patch numbers, so the next bump won't need test edits. The image builds, and each Node version runs the package manager, the Claude CLI and the sandbox tool as the restricted user.

One step is left, and it can only happen after merge: redeploying the runtime so production uses the new image.

## Per-AC Results

| AC-ID | Description | Codebase evidence | Workstream / docs evidence | Test evidence | Result |
| ----- | ----------- | ----------------- | -------------------------- | ------------- | ------ |
| AC-1 | Dockerfile `ARG NODE_VERSIONS`/`NODE_DEFAULT` and `node.py` `NODE_VERSIONS`/`DEFAULT_NODE` name the three new versions; the pinning test passes | `Dockerfile:91-92` `"22.23.5 24.22.3 26.13.1"` / `26.13.1`; `node.py:49,51` `("22.23.5", "24.22.3", "26.13.1")` / `"26.13.1"`. They agree. | Runbook steps 2-3 | `test_node.py::TestShippedVersions::test_dockerfile_installs_exactly_the_shipped_versions` and `test_dockerfile_pins_a_sha256_per_version` pass (part of `make validate`, re-run here: 3358 passed) | Pass |
| AC-2 | Each linux-arm64 SHA-256 comes from its release's `SHASUMS256.txt`; `sha256sum -c` passes in the build | `Dockerfile:96-98`. This audit fetched `https://nodejs.org/dist/v<v>/SHASUMS256.txt` for each version. The linux-arm64 entries are `8bd3dc69…bdba3` (22.23.5), `261af2af…affe8` (24.22.3) and `80a330b3…cc7d` (26.13.1), and all three are **byte-identical** to the pins. | Runbook step 1. `dist/index.json` confirms each one is the latest patch on its major: v22.23.5 2026-11-11 Jod, v24.22.3 2026-11-10 Krypton, v26.13.1 2026-11-10 Lithium. | The image built in this session. The Node install layer (#6) was **CACHED** from the author's earlier build, so `sha256sum -c` did not run again here. That cached layer's RUN text contains the new SHAs, so it is the same instruction that passed before. The independent upstream match above is the main evidence. | Pass |
| AC-3 | `make validate` and `make image-smoke` pass; each `/opt/node/<major>` runs pnpm, claude and srt as `fixer` | No code beyond the pins | Runbook step 5 | Re-run here: `make validate`: lint, format-check, typecheck, tests (3358 passed, 1 skipped, 5 xfailed; coverage 97.84%) and pip-audit all passed. `make image-smoke`: "63 checks passed", including `ok: node v22.23.5 at /opt/node/22 (fixer; pnpm, claude and srt run on it)` and the same line for v24.22.3 and v26.13.1 | Pass |
| AC-4 | Tests take their shipped versions from `NODE_VERSIONS`, so a later patch bump doesn't break them | `test_node.py:68`; `test_sandbox.py:32,318,325,340,351` | n/a | All four literals that a patch bump would break are now derived (see "Test changes"). The literals left in `test_node.py:111-182,233` and `test_node_hostile.py:197-206` are inputs to `satisfies()` range checks and to `NodeChoice(...).major`. Neither function checks membership in `NODE_VERSIONS` (`node.py:68-78,187-193`), so they still pass after a bump. Only `bin_dir()`/`node_path()` check membership, and every call to them now uses `NODE_VERSIONS` | Pass |
| AC-5 | After merge, the runtime is redeployed through `/infra-engineer` | n/a | Runbook step 6 ("Deploy as above") names the deploy path | Can't be checked before merge | Pending (post-merge, by design; this doesn't make the audit `blocked`) |

### Runbook "Add or bump a Node.js version in the image" (`docs/runbooks/bug-fix-agent.md:106-117`)

| Step | Status | Evidence |
| ---- | ------ | -------- |
| 1. Release from `index.json`, SHA from `SHASUMS256.txt` | Done | Matched independently (AC-2) |
| 2. Dockerfile `NODE_VERSIONS`, `node-sha256.txt` lines, `NODE_DEFAULT` | Done | `Dockerfile:91-98`. Majors are still one each, in ascending order. |
| 3. `node.py`; `ALLOWED_PATHS` and refusal phrase only on a major change | Done; the major-only parts rightly don't apply | `fixer_exec.py:36-41` still lists `/opt/node/{22,24,26}/bin`. `refusal.py:152` still says "must accept Node 22, 24 or 26". Both are pinned by tests (`test_the_refusal_phrase_names_the_shipped_majors`, the `ALLOWED_PATHS` equality test in `test_sandbox.py`) |
| 4. pnpm / claude-code / sandbox-runtime engines accept the majors | Done, no change needed | `npm view`: `pnpm@10.11.0` `>=18.12`; `@anthropic-ai/claude-code@2.1.309` `>=22.0.0`; `@anthropic-ai/sandbox-runtime@0.0.81` `>=22.12.0`. All accept 22.23.5, 24.22.3 and 26.13.1. The pins are unchanged (`Dockerfile:124-126`). |
| 5. `make validate && make image-smoke` | Done | AC-3 |
| 6. Deploy | Pending (post-merge) | AC-5 |

### Spec intent (§8.7 "Node", D-113)

D-113 and the §8.7 "Node" subsection are **not on `main`** and not on this branch. They live on `docs/471-drift-write-back` (PR #483, open; spec v2.9). That text names majors only: "ships Node 22, 24 and 26 … 26 the default". It has no patch literals (checked with `git grep` on that branch). A patch bump that keeps the majors and the default matches D-113, and nothing will conflict when #483 merges.

## Test changes (weakening check)

| Location | Before | After | Expected value (still a literal) |
| -------- | ------ | ----- | -------------------------------- |
| `test_node.py:68` `test_bin_dir_is_under_the_root_by_major` | `bin_dir("24.22.2")` | `bin_dir(NODE_VERSIONS[1])` | `"/opt/node/24/bin"` |
| `test_sandbox.py:325` `test_node_path_puts_the_major_bin_first` | `node_path("24.22.2")` | `node_path(NODE_24)` | `"/opt/node/24/bin:" + FIXER_PATH` |
| `test_sandbox.py:340` `test_build_env_with_node` | `node="22.23.4"` | `node=NODE_22` | `"/opt/node/22/bin:" + FIXER_PATH`, env key set unchanged |
| `test_sandbox.py:351` `test_run_passes_the_node_path` | `node="24.22.2"` | `node=NODE_24` | `"/opt/node/24/bin:" + FIXER_PATH` |

The expected values are unchanged, so no assertion got weaker. The old literals did one more thing: they implied that a particular patch was shipped. That is now covered on its own by the Dockerfile-to-`node.py` equality test and the per-version SHA test. `NODE_22, NODE_24, _ = NODE_VERSIONS` (`test_sandbox.py:318`) and `NODE_VERSIONS[1]` depend on order and on there being three entries. `test_three_majors_full_versions_ascending` pins both (`[22, 24, 26]`). If a major is added, the unpack fails loudly when the module is collected. That is a fail-closed guard, not a silent pass, and adding a major already means editing `ALLOWED_PATHS` and the refusal phrase.

## Stale-version sweep

`git grep` for `22.23.4`, `24.22.2` and `26.12.1` (and for the bare `22.23`, `24.22` and `26.12`) outside `infra/changes`, cdk.out and caches:

| Hit | Disposition |
| --- | ----------- |
| `docs/technical-guidelines.md:77` (changelog row 1.59) | History, left as is |
| `docs/runbooks/bug-fix-agent.md:44` (`… Got: v26.12.1` (run `fb717a51`, 2026-10-30)) | A quoted historical error message, not a current claim |
| `workstream/spike-bug-fix-sandbox.md:45` | Dated spike record |
| `workstream/fidelity-report-471.md` | History |
| `test_node.py:111-182,233`, `test_node_hostile.py:197-206` | Inputs to range and major checks; they don't depend on the shipped set (AC-4) |
| `TESTING.md:219` (and archived reports) "Node 22.23.2" | The panel's CI Node, which has nothing to do with the bug-fix image |

No doc, runbook, spec or `TESTING.md` text names an old patch as the current one. The current-state text (runbook L44, technical-guidelines §9 row) names majors only. `scripts/image-smoke.sh:95` reads the versions from the Dockerfile.

## Drift Catalog

**None.** No Critical, Major or Minor drift.

Observations (not drift, no action needed):

- **O-1.** The runbook's `last_verified: 2026-10-30` wasn't bumped, although this PR ran the procedure. That is 28 days, well within the 90-day staleness window. Optional: `technical-writer` can bump it the next time the runbook is touched.
- **O-2.** The caller's spec reference (§8.7 "Node", D-113) is only on open PR #483. This PR doesn't conflict with it (see "Spec intent").

## Edge-Case and Randomized Test Outcomes

There is no Design Mode test plan for #510, so none was run. The existing hostile and property-style `node` tests ran green as part of `make validate`.

- **Documentation structure.** `core/checks` isn't in this repository, so `checkDocsStructure` couldn't run. The touched runbook has valid frontmatter, and `last_verified` is 28 days old, so it isn't stale (see O-1).
- **Vocabulary conformance.** `checkExportedIdentifiers` couldn't run because `core/checks` is absent. The diff also adds no `export` declarations, since the changed code is Python. No findings.
- **Runbook coverage (FR-49b).** Not a finding. The PR follows an existing documented procedure, which needs no change, and it doesn't touch `templates/scripts/`, `templates/workflows/` or `.github/workflows/`.
- **Roadmap.** Not a finding. This is a chore under the Phase 5 milestone, and it completes no PRD phase or wave.

## Recommendations

| Item | Next step | Owner |
| ---- | --------- | ----- |
| AC-5 | After merge, redeploy the runtime through `/infra-engineer` (runbook "Deploy"). Then check that a run's `repo gate passed (… node <version>)` event names a new patch. | `infra-engineer` (operator) |
| O-1 | No action needed. Optionally bump `last_verified` on the next runbook edit. | `technical-writer` |
| O-2 | No action needed for this PR. | — |
