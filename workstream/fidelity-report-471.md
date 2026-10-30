# Fidelity Report — #471 (bug-fix: select the Node.js version per repo)

> **Fidelity: High** · **Highest drift impact: Major** (spec write-back needed, Intended) · **Blocking findings: none**
> Scope: issue [#471](https://github.com/llipe/dev-tasks-agent-fleet/issues/471), draft PR [#472](https://github.com/llipe/dev-tasks-agent-fleet/pull/472), branch `fix/471-bug-fix-node-version` (`4ebfe69`, `b824346`) vs `main` (`448eda6`).
> Every drift item below is **non-blocking**: it does not hold PR readiness or the issue's completion. Drift routes to `product-engineer` (`activity-drift-reconciliation`), and code fixes go to `developer`.

## Changelog

| Version | Date | Summary | Author |
| ------- | ---- | ------- | ------ |
| 1.0 | 2026-10-30 | Initial pre-PR-ready audit (Audit Mode). | verifier |
| 1.1 | 2026-10-30 | Developer resolution of DF-471-02/03/05/07/09 (see §Resolution). | developer |

## 1. Human-readable summary

Bug-fix could not work on any repository that required a Node.js version other than 26. The container only had Node 26, so the dependency install failed straight away (run `fb717a51`).

The fix ships three Node versions side by side: 22, 24 and 26. They come from the official Node.js downloads, and each download is checked against a fixed fingerprint. Before running anything from the repository, the agent reads which Node versions the repository accepts and picks one. It then runs the install and every check on that version. If the repository accepts none of the three, the agent now declines politely and names the reason ("missing a supported Node.js version"). Before, it crashed with an install error. Repositories that don't pin a version behave exactly as before, on Node 26.

Every acceptance criterion is delivered and the quality gates pass. The audit found three kinds of follow-up:

- **The specification needs updating.** It lists, as a fixed contract, which repository requirements the agent checks and the exact wording of each refusal. It also describes the environment the agent's helper processes get. This change adds a requirement and changes how that environment is built, but those documents were not updated. This needs a write-back, not a code change.
- **Two small edge cases differ from the issue's wording.**
  - The issue says a version rule the agent can't read falls back to the default (26). In fact, a `.nvmrc` file can still pick 22 or 24 in that case.
  - A few malformed version rules that pnpm itself rejects are read by the agent anyway. One of them can lead to a refusal where the issue says the agent should fall back to the default.
- **Safety evidence is now thinner for repositories on Node 22 or 24.** The sandbox launcher was safety-tested on Node 26 in the S-182 spike. For repositories pinned to 22 or 24, it now runs on that older Node, which has only been smoke-tested ("it starts"), not safety-tested.

## 2. Per-AC result table

| AC-ID | Description | Codebase evidence | Workstream/doc evidence | Test evidence | Result |
| ----- | ----------- | ----------------- | ----------------------- | ------------- | ------ |
| AC-1 | Node 22/24/26 under `/opt/node/<major>` from official nodejs.org builds with pinned SHA-256; NodeSource gone; Node 26 stays `/usr/bin/node` | `Dockerfile:83-127`: `ARG NODE_VERSIONS="22.23.4 24.22.2 26.12.1"`, `sha256sum -c` before unpacking, `install -o root`, `tar --no-same-owner`, `chmod -R go-w`, symlinks `/usr/bin/{node,npm,npx}` → `/opt/node/26`, a version check per tarball. `npm install -g --prefix /usr` keeps pnpm/claude/srt out of `/opt/node`. No `nodesource` anywhere. | README image section; runbook L44; tech-guidelines 1.59 | `test_node.py:74-98` (Dockerfile versions = `NODE_VERSIONS`; one SHA line per version; no NodeSource); `image-smoke.sh` passed against the built image (reported by caller; **not re-run by verifier**) | **Pass** |
| AC-2 | Repo gate picks a Node from the base commit before repo code runs; `engines.node` first; `.nvmrc` then `.node-version` narrow, never widen; else the default if it fits, else the highest; an unparseable `engines.node` → the default, as before | `toolchain.py:501` calls `select_node(reader)` on `safe_git.TreeReader` (base commit, before install); `node.py:225-246` | README repo-gate paragraph | `test_node.py:178-238`, `test_node_hostile.py`; differential fuzz by the verifier (§5) | **Drift** (DF-471-02, DF-471-03): the core behaviour passes; two edge cases diverge from the AC's wording |
| AC-3 | `engines.node` accepting no shipped version → refused by name ("supported Node.js version"), not `INSTALL_FAILED` | `toolchain.py:109,502-503,509-511` (no toolchain, so install never runs); `refusal.py:126,151-153` | runbook L44 | `test_toolchain.py:382-397`; `test_checkout.py:345-349` (fixture `js-node-unsupported`, `>=30`); `test_s189_fix_round_gate.py:172-181` (phrase set = item set) | **Pass**; spec contract drift is DF-471-01 |
| AC-4 | Install and every gate run with the chosen Node first on `fixer`'s PATH; `fixer_exec.py` accepts a PATH only from a fixed allowlist | `checkout.py:321-328` (install `node=`); `gates.py:130-132` (every gate, so base and final); `sandbox.py:91-102,319-335,465` (env built before any preflight, `ValueError` for an unshipped version); `fixer_exec.py:36-41,52-53` | README install paragraph | `test_sandbox.py:316-386` (`fixer_exec.ALLOWED_PATHS == sandbox.ALLOWED_PATHS`; a hostile PATH is reset); `test_checkout.py:429-447` (every sandbox call gets 24.22.2; Python gets `None`) | **Pass**; spec env drift is DF-471-04 |
| AC-5 | `image-smoke.sh` checks every shipped Node, also as `fixer`, and that `/opt/node` has no writable entries; runbook has an "add or bump a Node version" procedure | `image-smoke.sh:94-111` (default version; each `/opt/node/<major>` as root and as `fixer` through `fixer_exec.py` under `no-new-privileges`, with pnpm/claude/srt on it; `find -perm /022`) | `docs/runbooks/bug-fix-agent.md:106-120` (six steps plus rollback), `last_verified` and trigger updated | caller-reported smoke pass (63 checks) | **Pass** (minor gap: DF-471-07) |
| AC-6 | Gates pass: pytest with coverage ≥ 90%, ruff, ruff format, mypy, pip-audit. Test first | — | `TESTING.md` bug-fix line (98%) | **Re-run by verifier:** `make validate` → 3350 passed, 1 skipped, 5 xfailed; coverage **97.84%** (`node.py` 99%, `fixer_exec.py` 100%, `sandbox.py` 99%); ruff, format (89 files), mypy (89 files) and pip-audit all clean. `qa-engineer` `coverage_gate: PASS` | **Pass**. Test-first is not evidenced from history: tests and code land in the same commit `4ebfe69` |

AC coverage: 6/6 ACs have a result. Traceability `AC → test → observed → result`: AC-1 → `test_node.py::TestShippedVersions` → pass; AC-2 → `TestSelectNode`/`TestSatisfies` + fuzz → pass with drift; AC-3 → `test_toolchain.py::test_unsatisfiable_engines_node_is_a_named_miss`, `test_checkout.py[js-node-unsupported]` → pass; AC-4 → `test_sandbox.py::TestNodePath`, `test_checkout.py::test_install_and_gates_run_on_the_repos_node` → pass; AC-5 → `image-smoke.sh` (caller-reported) → pass; AC-6 → `make validate` re-run → pass.

## 3. Drift catalog

All items are **advisory and non-blocking**.

### DF-471-01 — Spec §8.7 repo-gate contract and PRD FR-6 gain an item that isn't written back
- **Impact:** Major · **Intent:** Intended
- **Evidence:** `refusal.py:126,151-153`, `toolchain.py:109,116,501-503`. Spec `workstream/specification-prd-bug-fix-agent.md:328-347` lists the item set and the fixed reply phrases as a contract (`refusal.REPO_GATE_ITEMS`, `REPO_GATE_PHRASES`; D-112 amendment, DF-189-04/05). The new item is missing from it:
  - `supported Node.js version`;
  - its phrase, "missing a supported Node.js version (`engines.node` must accept Node 22, 24 or 26)";
  - the JS gate condition (spec L330);
  - where the item sits in the miss order: after the manager/lockfile, before the scripts. `REPO_GATE_ITEMS` appends it last, which is harmless because that tuple is only a membership set.

  PRD `docs/requirements/prd-bug-fix-agent.md:93` (FR-6, "applicable only if …") now has an extra applicability condition. FR-5(e) still holds.
- **Not a contradiction:** the reply format, the "first missing item" rule, "no phrase holds user text", and `MISS_ITEMS ⊆ REPO_GATE_ITEMS` all still hold. The phrase is a constant.
- **Write-back needed:**
  - spec §8.7: a table row, the JS bullet, and the Node selection rules (engines → `.nvmrc` → `.node-version` → default 26 → highest; an unparseable range keeps every candidate);
  - a new spec changelog row (v2.9);
  - a D-112 amendment or a new decision;
  - a note on PRD FR-6 (a PRD changelog row, human-confirmed);
  - the S-189 AC5 wording in `user-stories-prd-bug-fix-agent.md:529`.

### DF-471-02 — An unparseable `engines.node` does not always mean "the default, as before"
- **Impact:** Minor · **Intent:** Undetermined
- **Evidence:** `node.py:231-243`. When the range fails to parse, every shipped version stays a candidate, and a `.nvmrc`/`.node-version` can still pick one. Verifier probe: `engines.node: "lts/*"` + `.nvmrc: 22` → `NodeChoice('22.23.4', '.nvmrc')`. The AC says "the default is used, as before", and before this change it was always 26. The behaviour is documented on purpose (`node.py:16-18`; README says "keeps every shipped version, as before"), but the only test is `test_node.py:203-205`, which has no version file.
- **Recommendation:** `product-engineer` decides which reading is intended. If the delivered behaviour is accepted, amend the AC/spec wording. If not, `developer` makes an unparseable range return the default and ignore version files.

### DF-471-03 — The range parser accepts ranges that node-semver (and so pnpm) rejects
- **Impact:** Minor · **Intent:** Unintended
- **Evidence:** `node.py:114-118` ("24.x.3 is 24.x") normalises a numeric part after a wildcard. node-semver 7.8.5 rejects `24.x.3`, `x.24`, `*.23.25` and `24.*.1` as invalid. The docstring `node.py:29-33` claims node-semver's grammar. Consequences:
  - `engines.node: "30.x.1"` is refused as `supported Node.js version`, where AC-2 says an unparseable range → the default;
  - `"x.30"` is read as `*`.
- **Differential fuzz** (verifier; seeds `4711` and `9001`, ~7,900 generated ranges against the three shipped versions, `semver@7.8.5` from the root `node_modules`):
  - wherever node-semver parses a range, results agree in **6,233/6,233** cases;
  - all **1,672** disagreements are ranges node-semver rejects and `node.py` accepts, every one with a wildcard followed by a number.
  - Replay: scratchpad scripts `gen.py <seed> specs.json` → `ref.js` → `cmp2.py`, described in §5.
- Unrealistic input, so Minor.
- **Recommendation:** `developer`: raise `RangeError` when a numeric part follows a wildcard part, and add the fuzz cases as table tests.

### DF-471-04 — Spec env/allowlist text (§7, §8.7, §12, D-51/D-110) doesn't describe the PATH allowlist
- **Impact:** Minor · **Intent:** Intended
- **Evidence:** Before this change, `fixer_exec.build_env` always forced `PATH=/usr/local/bin:/usr/bin:/bin`. Now it keeps an incoming PATH if it is one of four values (`fixer_exec.py:36-41,52-53`), equal to `sandbox.ALLOWED_PATHS` (`sandbox.py:99-102`) and pinned by `test_sandbox.py:362`. The env **name** set is unchanged (`ANTHROPIC_API_KEY`, `PATH`, `HOME`, `LANG`, `CI`), so spec L367, L199 and L525-526 and D-51 layer 1 still hold as written. No security regression:
  - the set is closed;
  - every entry is a root-owned directory;
  - anything else is reset.

  Still, D-110's "rebuilds it from that allow-list" now means "and keeps PATH only from a closed value set". The spec doesn't say so. §8.1 also lacks the new module `node.py`, and the `sandbox.py`/`fixer_exec.py` rows don't mention `node=`/`ALLOWED_PATHS` (spec L206-233).
- **Write-back needed:** spec §8.1 (a `node.py` row), §8.7 env bullet, §12 item 1, and a dated note on D-110 (or a new decision for the per-repo Node).

### DF-471-05 — `srt`, the repo-script confinement launcher, now runs on the repo's Node; the spike evidence covers Node 26 only
- **Impact:** Minor · **Intent:** Undetermined
- **Evidence:**
  - `sandbox.py:204,438` runs `/usr/bin/srt`, a `#!/usr/bin/env node` script, so with `/opt/node/<major>/bin` first on PATH (`sandbox.py:465`), srt and its filtering proxy run on Node 22 or 24 for repos pinned there. The Dockerfile comment at L117-123 acknowledges this.
  - The S-182 spike evidence (39/39, spec L574) and spec §12 item 3 (L532) were gathered with srt on Node 26.
  - Image smoke (`image-smoke.sh:105`) only runs `srt --version` on each Node. It does not exercise a denied read, a denied write or the network allowlist.
- **Recommendation:**
  - `developer`: launch srt with an explicit interpreter (`/usr/bin/node /usr/bin/srt …`). This keeps the confinement layer on the verified Node, while the command inside still gets the repo's PATH.
  - Alternatively, extend image smoke to assert one srt deny per shipped Node.
  - `product-engineer`: note the residual in spec §12 if it is accepted.

### DF-471-06 — The Wave B follow-up ("the fixer CLI run should pass `node=`") is not tracked
- **Impact:** Minor · **Intent:** Intended
- **Evidence:** The issue #471 Notes ask that S-191's fixer CLI run pass `node=toolchain.node_version`. Issue #373 (S-191) does not mention Node, and nothing else tracks it. Without it, the model's Bash calls (for example `pnpm test`) in an engine-strict repo would run on Node 26 and fail the same way. Validation and base/final gates are covered: `gates.py` passes `node=`. S-193's red-to-green changed-test runs need the same.
- **Recommendation:** `product-engineer`: add a task to S-191 (#373) and S-193 (#375), and a line to spec §8.7 "fix".

### DF-471-07 — The `/opt/node` writability check tests permission bits, not ownership or `fixer`'s view
- **Impact:** Minor · **Intent:** Unintended
- **Evidence:** `image-smoke.sh:109-111` runs as the default user (root) and checks `-perm /022` only. A `fixer`-owned file with `u+w` would pass, yet the success message says "not writable by fixer". The risk is mitigated at build time (`Dockerfile:106-107`: `install -o root`, `tar --no-same-owner` as root, `chmod -R go-w`).
- **Recommendation:** `developer`: add `! -user root` to the `find`, or run `find /opt/node -writable` as `fixer`.

### DF-471-08 — The foundation doc was updated under its old name
- **Impact:** Minor · **Intent:** Intended
- **Evidence:** `docs/technical-guidelines.md:77` (changelog 1.59). `docs/tech.md` does not exist, so writing to the old name avoided splitting the document. CLAUDE.md FR-45 says to write the new name and propose `dev-tasks migrate docs`. The same applies to `docs/product-context.md`.
- **Recommendation:** `technical-writer` / the user: run `dev-tasks migrate docs` separately. No change in this PR.

### DF-471-09 — PR #472 metadata is stale
- **Impact:** Minor · **Intent:** Unintended
- **Evidence:**
  - The PR body says `make validate: 3315 passed`; it is 3350 after `b824346`.
  - `coverage_gate: pending` and `verifier audit: pending` are still there; it should be `coverage_gate: PASS` plus this report.
  - The PR has no milestone, while #471 is on `v5.0 — Phase 5 Bug Fix Agent`.
- **Recommendation:** `developer`/`github-ops`: refresh the PR body and set the milestone before marking it ready.

### Not findings (checked)
- **Runbook in the same PR (FR-49a / FR-49b):** delivered. `docs/runbooks/bug-fix-agent.md:44,106-120`, with the trigger and `last_verified` updated. Strictly, the FR-49a scope (templates/scripts, workflows, infra-engineer changes) isn't triggered, but the procedure ships anyway. No runbook-coverage finding.
- **Roadmap:** the change completes no phase or wave. The Wave A row (`docs/roadmap.md:11`, Done) stays correct. Optional: list #471 under Wave A follow-ups. No roadmap-mismatch finding.
- **Gate event fields:** `checkout.py:305-314` adds `node` and `node_source` to the `repo gate passed` `run_event`. Spec §13 (L583) doesn't enumerate event fields, and the change is additive, so no contract break.
- **Image pinned-toolchain requirements:**
  - Python 3.13, pnpm 10.11.0, CLI 2.1.309 and srt 0.0.81 are unchanged.
  - `setpriv` present and no `sudo` are still enforced by the build.
  - `libatomic1` is a new apt dependency, documented.
  - Story S-180's AC text "Node 26 + pnpm" (`user-stories-prd-bug-fix-agent.md:57`) is now stale. Fold it into the DF-471-01 write-back.
- **`REPO_GATE_ITEMS` order:** a membership/allow set (`refusal.py:225`). The appended position changes no rendering, and the first-miss order comes from `check_repo_gate`.

## 4. Documentation structure and vocabulary

- **Docs structure:** `core/checks` (`checkDocsStructure`) is not present in this repository, so the check could not run and was not re-derived by hand. No result.
- **Vocabulary conformance:** `checkExportedIdentifiers` is not available. `docs/domain/ubiquitous-language.md` has no terms yet, so nothing is forbidden. No findings.

## 5. Randomized test outcomes

- **Property:** for every range, `node.satisfies(v, r)` equals node-semver `Range(r).test(v)` for `v` in `NODE_VERSIONS`, where node-semver parses `r`.
- **Seeds:**
  - `4711`: 3,951 ranges; 3,111 agree, 840 are ranges node-semver rejects and `node.py` accepts.
  - `9001`: 3,954 ranges; 3,122 agree, 832 likewise.
  - No disagreement among ranges both sides parse.
- **Replay:**
  1. `python3 -I gen.py <seed> specs.json`
  2. `node ref.js <repo>/node_modules/.pnpm/semver@7.8.5/node_modules/semver specs.json > ref.json`
  3. `python3 -I cmp2.py agents/bug-fix/app/bugFix ref.json`

  The scripts live in the verifier's session scratchpad and are not committed.
- **Minimised failing input:** `24.x.3` (node-semver: invalid; `node.py`: `>=24.0.0 <25.0.0-0`). Classification: implementation defect (DF-471-03).

## 6. Recommendations

| Item | Next step | Owner |
| ---- | --------- | ----- |
| DF-471-01 | Spec §8.7 and §8.1, PRD FR-6 note, S-189/S-180 story text, decision amendment, changelogs (human-confirmed) | `product-engineer` |
| DF-471-02 | Confirm the intended reading; amend the AC/spec text or route a code fix | `product-engineer` (then `developer` if needed) |
| DF-471-03 | Reject wildcard-then-number partials; add table tests | `developer` |
| DF-471-04 | Spec §7/§8.7/§12 env text; D-110 dated note | `product-engineer` |
| DF-471-05 | Run srt on `/usr/bin/node` explicitly, or add per-Node srt deny smoke checks; note the residual in §12 | `developer`, then `product-engineer` |
| DF-471-06 | Add `node=` tasks to S-191 (#373) and S-193 (#375) | `product-engineer` |
| DF-471-07 | Ownership/`fixer`-view check in image smoke | `developer` |
| DF-471-08 | `dev-tasks migrate docs` (separate change) | `technical-writer` |
| DF-471-09 | Refresh the PR body gates and test count; set the milestone | `developer` / `github-ops` |

## Resolution (developer, v1.1)

| Item | Status | Change |
| ---- | ------ | ------ |
| DF-471-02 | Kept, now tested | Intended: an unparsed `engines.node` is treated as no `engines.node`, so `.nvmrc` / `.node-version` still narrow. `test_node.py::test_an_unparseable_range_still_lets_a_version_file_choose`; the PR body states the reading. |
| DF-471-03 | Fixed | `node._parse_partial` raises `RangeError` on a number after a wildcard (`24.x.3`, `x.30`, `30.x.1`), as node-semver does; table cases added; the hypothesis generator emits only well-formed partials. |
| DF-471-05 | Fixed | `SandboxPaths.node = "/usr/bin/node"`; script mode runs `/usr/bin/node /usr/bin/srt …`, so srt and its proxy stay on the default Node regardless of PATH. `check_available(SCRIPT)` requires it. Checked in the built image: the srt process is `/usr/bin/node /usr/bin/srt`, the command inside reports `v24.22.2`. |
| DF-471-07 | Fixed | `image-smoke.sh` also checks `/opt/node` is root-owned and that `fixer` (through setpriv) finds nothing `-writable`. |
| DF-471-09 | Fixed | PR body refreshed; milestone set. |
| DF-471-01, -04, -06 | Open | Spec/PRD/story write-back and Wave B tasks: route to `product-engineer` (`activity-drift-reconciliation`). |
| DF-471-08 | Open | `dev-tasks migrate docs`, separate change. |

## Publication

Committed with PR #472; the verdict header is posted on the PR.
