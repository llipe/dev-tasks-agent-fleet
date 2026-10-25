# Fidelity Report — S-189 (#371): Checkout, repository gate, toolchain, and the gate runner

**Fidelity: High** · **Highest drift impact: Minor** (9 findings, all Minor; none blocking)
**Scope:** S-189 / #371 · Draft PR #458, `story/S-189-checkout-gates` @ `af142db` → `integration/bug-fix-agent-wave-a` @ `54d27c4` (includes #459)
**Mode:** verifier Audit Mode (grey-box) · 2026-10-24 · drift is advisory and **non-blocking** to PR readiness and issue completion; findings route to `product-engineer`'s `activity-drift-reconciliation`.

---

## 1. Summary

This story gives the bug-fix agent its "can I work here?" step. The agent makes a private copy of the target repository, hands a plain-file copy to the restricted `fixer` account, and checks for the agreed developer guide and the four quality checks. For Python repositories it also checks for an `install` step. If anything is missing, the agent posts one short reply on the issue and stops. Nothing else on the issue changes. If everything is present, the agent installs dependencies without changing lock files, then runs the checks once on the untouched code and records the results, which never stop the run. Last, it undoes anything those runs changed, so the AI starts from an exact copy of the base code.

Everything requested was delivered. CI is green on the PR head, and I re-ran the story's 643 tests locally. The developer flagged five deviations, and all five hold up. The biggest one was needed: the base copy is built from git's raw file contents instead of `git archive`. `git archive` follows a repository's own export rules, which can drop or rewrite files. That would break the promise of an exact base copy.

What is left is wording and edge cases:
- The refusal reply for the new Python rule says "missing `install`" rather than "missing install target".
- The "files restored" count also includes new files that were removed.
- A few planning documents still name a `wrapper` user that no longer exists.
- Some repository shapes (a Python repo with a root `package.json`, a `Makefile` that pulls in targets with `include`) are refused, by design, and should be named in the runbook.

Two tests, TC-189-08 and TC-189-21, need the run orchestration from S-190. Deferring them matches the test plan.

---

## 2. Per-AC results

Sources: (C) the codebase diff, (W) `/workstream` artifacts and the task list, (T) tests, (S) PRD, spec and decision intent.

| AC-ID | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
| ----- | ----------- | ----------------- | ------------------- | ------------- | ------ |
| S-189-AC1 | Shallow clone into `/work/wrapper/repo` (0700), base SHA, `info/exclude` = 4 dependency dirs (D-62, D-83) | `safe_git.clone()`: `--depth=1 --single-branch --no-checkout --no-tags --template=`, `chmod 0700`, `write_exclude()` (`EXCLUDE_LINES`), `base_sha = rev_parse("HEAD")`; `checkout.github_url()` builds a token-free URL | Task 10.13 and 10.14 checked; the uid is per D-110 (root) | `test_checkout.py::TestClone` (TC-189-01), `TestNoTokenAtRest` (TC-189-02), `TestCloneFailure` (TC-189-03); `image-smoke.sh` `clone_mode=0o700`, `clone_owner=0` | **Pass**. The AC text still says uid `wrapper` (DF-189-07) |
| S-189-AC2 | Hardened `safe_git.py`, no `safe.directory`, no git on a `fixer`-writable `.git` | `HARDENED_ARGS` and `HARDENED_ENV` (env from scratch, `HOME=/nonexistent`); `--attr-source=<empty tree>`; explicit `--git-dir`; `cwd=clone_dir`; no `-C`/`GIT_DIR` | 10.12 and 10.13 | `test_git_confinement.py::TestHardened` (TC-189-16 spawn spy over clone, archive, capture and restore), `tests/unit/test_safe_git.py` (static scan: no git outside `safe_git.py`) | **Pass** |
| S-189-AC3 | Base tree materialized into a fresh `/work/repo` by `tar -x` as `fixer`; plants never run | `SafeGit.materialize(fresh=True)`: tar built from `ls-tree` + `cat-file --batch` and streamed to `tar -x` behind `fixer_prefix` (setpriv) | 10.13, 10.14; D-62 says `git archive` | `TestMaterialize` (TC-189-18, incl. `test_export_attributes_are_not_applied`), `TestPlantedRepoNeverRuns` (TC-189-17, hooks, fsmonitor, `diff.external`, filter, textconv, with a live control); image smoke `file_owner=10002`, `dotgit=False`, `canary=False`, `control=True` | **Pass**. The mechanism is intentionally not `git archive` (DF-189-01) |
| S-189-AC4 | `toolchain.py` copied from `dependency-update`, detects pnpm/npm or `Makefile` | Header cites `ff52835`; `detect_stack`, `detect_package_manager` | 10.5 | `tests/unit/test_toolchain.py::TestDetection`, `TestPrecedence` (TC-189-04, -05) | **Pass**. Precedence is pinned (DF-189-03) |
| S-189-AC5 | Repo gate: `developer.md` + four gates; a miss → refusal `repo_gate` naming it, before the claim | `check_repo_gate()` reads the **base commit** through `TreeReader` (regular blobs only); `checkout` → `refusal.post_refusal(Refusal("repo_gate", detail=first.item))`; no claim, reaction or board code in `checkout.py` | 10.4, 10.6, 10.8; TC-189-08/-21 mapped to `test_main.py` · 11.2 (S-190) | `test_checkout.py::TestRepoGate` (7 miss fixtures: exactly one POST, a marked `reason=repo_gate` block, no reaction, zero sandbox calls, `not_applicable`); `test_toolchain.py::TestRepoGate`, `TestMakeTargets` (TC-189-07, -09) | **Pass** (module scope). TC-189-08 orchestration half and TC-189-21 are S-190 per plan. See DF-189-03, -04, -05, -08 |
| S-189-AC6 | OQ-1 resolved as D-112: Python needs `make install`, else `repo_gate` "missing install target" before any issue change | `PY_INSTALL_TARGET`, `GateMiss.describe()` → "missing install target"; `INSTALL_ARGV["make"] = ("make","install")`; the gate runs before install | D-112 in the decision log (via #459); spec v2.5 §8.7, §16, §17; PR body cites it; 10.1 checked with the confirmation quote | `py-no-install` case in `TestRepoGate` (no sandbox call, one reply); `TestInstall::test_install_argv_per_manager[py-make-ok]` | **Pass**. The reply text is weaker than D-112's wording (DF-189-05) |
| S-189-AC7 | `gates.py`: four gates + `audit` through `sandbox.py`, `{pass, exit_code, tail}`, scrubbed tail | `run_gates()` in `Mode.SCRIPT`; `GateResult.to_dict()`; `scrubber.tail()` scrubs **before** cutting to 4,000 | 10.7 | `test_gates.py::TestArgv` (TC-189-11), `TestTail` (TC-189-12, incl. a secret straddling the cut and an unregistered token shape) | **Pass** |
| S-189-AC8 | Base results in `run_events`, kept for the PR body, never block | Each gate is a `run_event` with its result; `CheckoutResult.base_gates`; checkout proceeds regardless | 10.4 | `test_gates.py::TestBaseResults` (TC-189-13), `test_checkout.py::TestBaseGates` (red `make test` → `proceed`) | **Pass** |
| S-189-AC9 | Frozen install per manager; mismatch → `INSTALL_FAILED`, lockfile unchanged; restore base as `fixer` with a `run_event` | `INSTALL_ARGV`; `restore_base()` capture → `remove()` + `materialize(paths=…, fresh=False)` as `fixer`, up to 3 rounds; `run_event` "base runs modified N tracked files; restored" | 10.17, 10.18 | `TestInstall` (argv per manager, real `npm ci`, real `pnpm install --frozen-lockfile`, out-of-sync lockfile byte-identical, no issue write) (TC-189-14); `TestRestoreBase` (TC-189-15, incl. `.gitignore` hiding, same-size/same-mtime edit, symlink swap, real npm autofix) | **Pass**. N also counts removed untracked files (DF-189-06) |
| Business rule (FR-5) | No issue mutation before the repo gate passes | The only GitHub call in `checkout.py` is `post_refusal`; clone and install failures make no write | Task 10.0 note | `env.gh.writes() == []` on clone failure, install failure, out-of-sync lockfile, and ok fixtures; exactly one write on a miss | **Pass** |

**Focus checks requested by the caller**

| Check | Result | Evidence |
| ----- | ------ | -------- |
| D-112: Python without `make install` → `repo_gate` "missing install target" before any issue change; JS install frozen | Pass | `py-no-install` row in `TestRepoGate` (`sb.calls == []`, one POST); `INSTALL_ARGV` pnpm `--frozen-lockfile`, npm `ci`; `test_npm_install_is_never_plain_install` |
| No issue change before the repo gate (FR-5) | Pass | See the business-rule row |
| Base gate results recorded, never block (D-14) | Pass | AC8 |
| Tails scrubbed | Pass | `scrubber.tail()` scrubs the whole output, then cuts; gate and install tails and every `_failed()` summary go through `scrub_all` |
| `/work/wrapper` root 0700, unreadable by `fixer` | Pass | Dockerfile `root:root 0700` (3.17); image smoke `fixer_lists_wrapper=False`, `fixer_reads_config=False`. 53/53 on a local arm64 build (developer-reported; not re-run here: Docker) |
| Token never in argv or `.git/config` | Pass | `auth_env()` → `GIT_CONFIG_COUNT/KEY_0/VALUE_0` with `http.https://github.com/.extraheader`; `http.followRedirects=false`; `credential.helper=` reset; `TestNoTokenAtRest` checks `.git/config`, `FETCH_HEAD`, `packed-refs`, `logs/**`, and the argv |
| TC-189-08, TC-189-21 deferred to S-190 | Consistent with the plan | Test plan v2.3 maps both to `A/tests/component/test_main.py · 11.2`, and 11.2 is S-190's task. Test plan §11 item 8: "TC-189-21 waits on DF-35", and DF-35 is still open. S-189 already asserts the checkout-level shape (one marked reply, no reaction, no sandbox call), and `checkout.py` has no board dependency |
| Docs: README, TESTING.md, roadmap | README and TESTING.md accurate; roadmap row stale (observation) | README §"Checkout, repo gate and gates" matches the code step for step, including the raw-blob materialize and the `include`/precedence pins. TESTING.md names `repo_fixtures.py`, `SpawnSpy`, `StubSandbox`/`LocalSandbox`, the skip-when-missing rule, and the image-smoke additions. Roadmap: see OBS-189-01 |

---

## 3. Drift catalog

All items are **non-blocking** to PR #458 readiness and to #371 completion.

| ID | Description | Impact | Intent | Evidence |
| -- | ----------- | ------ | ------ | -------- |
| DF-189-01 | **Materialize builds the tar from raw blobs, not `git archive`** (developer deviation 1). Spec §8.7, D-62 (2) and task 10.13 say "`git archive <base>` piped into `tar -x` as `fixer`". The delivered `materialize()` lists the tree and reads each blob with `cat-file --batch`, then streams a self-built PAX tar into `tar -x` spawned as `fixer`. D-62's security property is kept: plain files, written only by `fixer`, no `.git`. The deviation is also *required* by D-63: `git archive` applies the repo's `export-ignore` and `export-subst` (and eol/ident conversion). With it, `/work/repo` would differ from the base tree, the D-63 capture would show spurious deletions or edits, and a restore through the same `git archive` could never converge. The spec's red-to-green steps 2 and 5 (S-193) still say `git archive` too. | Minor | Intended | `safe_git.py` `materialize()`/`_stream_tar()`; `test_git_confinement.py::TestMaterialize::test_export_attributes_are_not_applied`, `test_crlf_and_text_attributes_do_not_change_the_capture`; spec §8.7 `checkout` and `red_to_green` 2, 5; D-62 |
| DF-189-02 | **Materialize, capture, restore and repo-gate read faults map to `CLONE_FAILED`** (deviation 2). Spec §8.9 has one row: "Clone / install infra failure → `CLONE_FAILED` / `INSTALL_FAILED`". These are wrapper-side checkout steps, so `CLONE_FAILED` is the natural fit. One residual: a restore that doesn't converge in 3 rounds can be caused by repo scripts, yet it counts toward the breaker as infra. | Minor | Intended | `checkout.py` steps 2, 3, 6 → `_failed(CLONE_FAILED, …)`; `test_restore_that_cannot_converge_is_clone_failed`; spec §8.9 |
| DF-189-03 | **Stack precedence and `include` are pinned as the test plan asked** (deviation 3a, 3b). A root `package.json` wins over a `Makefile`, and `include` is not followed, because evaluating it would run repo code as root. TC-189-05 and TC-189-09 require a pinned behaviour, so this conforms. Two consequences are user-visible. (a) A Python repo with a root `package.json` for tooling (prettier, husky) is judged as JS. The D-112 `make install` contract is never consulted, and the refusal names four missing *scripts*. (b) A `Makefile` whose targets come from an `include` is refused with every target missing. Both behaviours were probed and confirmed. | Minor | Intended | `toolchain.py` `detect_stack`, `parse_make_targets`; probe: `py+package.json` → "missing script test; … typecheck", `include common.mk` → all five targets missing; README step 3 documents both |
| DF-189-04 | **`lockfile` and `package.json or Makefile` are new repo-gate items** (deviation 3c). Spec §8.7 lists only `developer.md` plus the four gates (plus `install` for Python). The delivered gate also refuses a JS repo with no supported lockfile, and a repo with no manifest. The refusal closed set grew by three items. Choosing a `not_applicable` refusal over a breaker-counted failure is reasonable, but the spec doesn't say it. The rule is also inconsistent. A `packageManager: "pnpm@…"` (or `npm@…`) field with no lockfile **passes** the gate, then fails the frozen install as `failed`/`INSTALL_FAILED`, which counts toward the breaker. And a yarn repo is told it is "missing `lockfile`" although it has one. | Minor | Undetermined | `toolchain.check_repo_gate` (`LOCKFILE_ITEM`, `MANIFEST_ITEM`); `refusal.REPO_GATE_ITEMS`; probe: `packageManager pnpm@9`, no lockfile → gate ok, install `pnpm install --frozen-lockfile`; `yarn.lock` → "missing lockfile (pnpm-lock.yaml or package-lock.json)"; spec §8.2 and §8.7 |
| DF-189-05 | **The refusal reply doesn't say "missing install target".** D-112 and spec §8.7 say the refusal names "missing install target". `result.summary` does, but the marked reply, the only thing the issue author sees, reads "this repository is missing `install`, which bug-fix needs…". It doesn't say whether that is a file, a script or a Make target. The same applies to `test` (script vs target) and to `lockfile`. | Minor | Undetermined | `refusal.REPLY_TEXT["repo_gate"]`; probe `reply_line(Refusal("repo_gate", detail="install"))`; D-112; spec §8.7 bullet 3 |
| DF-189-06 | **The restore count includes removed untracked files** (deviation 4). D-63 and spec §8.7 phrase the event as "base runs modified N tracked files; restored". The delivered N is every path that differed from base on the first capture, added untracked files included. TC-189-15's own test asserts "2 tracked files" for one tracked rewrite plus one new untracked file. The restore behaviour itself matches the spec ("plus `rm` for files they added"); only the label is off. | Minor | Intended | `checkout.restore_base()` returns `len(changed)` from the first capture; `TestRestoreBase::test_tracked_rewrite_and_untracked_file_are_restored`; D-63 (2) |
| DF-189-07 | **Planning artifacts still name a `wrapper` uid** (deviation 5). D-110 and spec §7 (v2.2+) removed the `wrapper` user: the wrapper is root and `fixer` runs through `setpriv`. The developer correctly reworded tasks 10.12, 10.13 and 10.15. Four sources still name the old user: stories v2.4 S-189-AC1 ("uid `wrapper`") and AC3 ("never runs as `wrapper`"); test plan v2.3 TC-189-01 ("owner `wrapper`"), TC-189-02 ("owned by `wrapper`") and TC-189-19 ("owned by `wrapper`"); the #371 issue body; and D-62 (1). The delivered code and smoke test follow D-110 (owner uid 0). | Minor | Unintended | `user-stories-prd-bug-fix-agent.md` S-189 AC1, AC3; `test-plan-prd-bug-fix-agent.md` TC-189-01, -02, -19; issue #371; D-110; tasks diff v2.0.9 |
| DF-189-08 | **The gate reads `Makefile` only.** GNU make reads `GNUmakefile`, then `makefile`, then `Makefile`. In a repo that has `GNUmakefile` or `makefile` next to `Makefile`, the repo gate approves the targets of one file while `make <target>` (install, base gates, later the final gates) runs another. The impact is bounded: everything runs as `fixer` in the sandbox, and a wrong gate ends in disposition, never a bad PR. But the gate verdict no longer describes what runs. | Minor | Undetermined | `toolchain.MAKEFILE = "Makefile"`, `detect_stack`; GNU make default-makefile order |
| DF-189-09 | **CI never runs the real `pnpm install --frozen-lockfile`.** The bug-fix `python-quality` job on `af142db` reports 2579 passed and **1 skipped**. Of the `skipif` tests, three need `npm` (present on `ubuntu-latest`) and one needs `pnpm` (not set up in the job), so the skipped one is `TestInstall::test_real_pnpm_frozen_install`. The real npm `ci` path and the out-of-sync lockfile check do run in CI. pnpm is covered only by the stubbed argv test and local runs (all 643 S-189-scope tests pass locally with pnpm present). | Minor | Unintended | CI run 40139564384, job 121008215325: "2579 passed, 1 skipped, 3 xfailed"; `.github/workflows/ci.yml` (no pnpm setup); `test_checkout.py:453` `skipif(not has("pnpm"))` |

**Observation (not a drift item): OBS-189-01, the roadmap Wave A row is stale.** The row's status, `In progress`, is correct. But its `Issues/PRs` column lists merged PRs only up to #449. Its `What's missing` still names S-186, S-185 and S-188, which merged through #451, #453 and #454. This sits outside the Roadmap-Mismatch trigger, because S-189 doesn't complete Wave A, so it isn't classified as drift. It is for `planner` to correct in the Wave A consolidated PR (or with S-190).

**Not findings.**
- *Runbook coverage:* the PR has one tooling step (10.15: Dockerfile and image smoke) and changes no script under `templates/scripts/` or any workflow, so it is below the threshold. The D-112 runbook prerequisite is assigned to S-197 (spec §16).
- *TC-189-08 and -21 deferral:* consistent with the plan (see the focus checks).
- *Branch currency:* the story branch is based on `5288f09` and lacks #459. #459 is docs-only and touches none of this PR's files, so no conflict is expected.

---

## 4. Edge-case and randomized test outcomes

| Edge case (story matrix, task 10.8) | Outcome |
| ----------------------------------- | ------- |
| Python `Makefile` with four gates, no `install` → "missing install target" | Pass (`py-no-install`) |
| `format_check` instead of `format-check` → missing | Pass (`py-format-underscore`, L1 and L2) |
| A `package.json` with no `scripts` | Pass (`js-no-scripts` → "missing script test", all four named in the summary) |
| A monorepo root `package.json` | Pass (`js-monorepo`; a workspace package alone doesn't satisfy the root) |
| A clone failure → `failed`/`CLONE_FAILED` | Pass (unknown branch, unreachable remote scrubbed, hostile branch names never reach git, existing clone dir) |
| An install failure → `failed`/`INSTALL_FAILED` | Pass (non-zero, timeout, unavailable sandbox, out-of-sync lockfile) |
| Symlinked `developer.md` | Pass (doesn't count) |
| Base run edits `.gitignore` to hide a new file; same-size, same-mtime edit; file → symlink swap | Pass (`TestRestoreBase`) |

No randomized or property tactic in the test plan targets S-189 (the plan lists none for this story). `test_toolchain.py` and `test_safe_git.py` are table-driven, and no seed is involved.

**Documentation structure.** `core/checks` (`checkDocsStructure`) isn't installed in this repository, so I couldn't run the check and didn't re-derive it by hand. The PR changes no file under `docs/`.

**Vocabulary conformance.** `docs/domain/ubiquitous-language.md` is `status: unfilled` and forbids no synonyms, so there are no findings. `checkExportedIdentifiers` isn't installed here either.

**Test execution (this audit).** I ran the S-189-scope tests from a `git archive` copy of `af142db` in the session scratchpad: `test_toolchain`, `test_safe_git`, `test_checkout`, `test_gates`, `test_git_confinement`, `test_safe_git_faults`, and `test_refusal` (unit and component). Result: **643 passed**, with git 2.56.0 and real npm and pnpm. CI is green on the same SHA (all 9 checks). I didn't re-run the image smoke (it needs Docker); the developer reports 53/53 on a local arm64 build, not deployed.

---

## 5. Recommendations

| ID | Next step | Owner |
| -- | --------- | ----- |
| DF-189-01 | Amend D-62 (2) and spec §8.7 (`checkout`, the base restore, and `red_to_green` steps 2 and 5) to say "a tar of the tree's raw blobs (no export or eol attributes), extracted by `tar -x` as `fixer`". Have S-193 reuse `SafeGit.materialize(paths=…)` rather than `git archive`. | `product-engineer` (spec write-back) |
| DF-189-02 | Add a note to spec §8.9: materialize, capture, restore and repo-gate read faults are `CLONE_FAILED`. Optionally say whether a non-converging restore should count toward the breaker. | `product-engineer` |
| DF-189-03 | No code change. Have the S-197 runbook state both pins as repository prerequisites: a root `package.json` makes the repo JS/TS, and `Makefile` targets must be literal, not included. | `product-engineer` → S-197 |
| DF-189-04 | Confirm `lockfile` and the manifest as `repo_gate` items, and add them to spec §8.7. If confirmed, make a `packageManager` field with no matching lockfile a `lockfile` miss too, so a lockfile-less repo is always refused rather than sometimes `INSTALL_FAILED`. Consider naming unsupported managers ("yarn is not supported"). | `product-engineer`, then `developer` |
| DF-189-05 | Give each `repo_gate` item a fixed reply phrase from the closed set ("the Make target `install`", "the `package.json` script `typecheck`", "a pnpm or npm lockfile"), so the reply matches D-112's "missing install target". Or accept the current reply and amend D-112's wording. | `developer` (or `product-engineer` to accept) |
| DF-189-06 | Either word the event "base runs changed N paths; restored", or report tracked and untracked counts separately. Then align D-63 and spec §8.7. | `developer` + `product-engineer` |
| DF-189-07 | Reword stories S-189-AC1 and AC3, test plan TC-189-01, -02 and -19, and the #371 body to the D-110 model (root wrapper, `/work/wrapper` `root:root` 0700, "never runs in the root wrapper's git"). Annotate D-62 (1) as amended by D-110. | `product-engineer` |
| DF-189-08 | Either refuse (or detect) a repo that has `GNUmakefile` or `makefile` beside `Makefile`, or pass `-f Makefile` to every `make` call so what runs is what was checked. Decide which, then pin it in a test. | `product-engineer` to decide, `developer` to apply |
| DF-189-09 | Add a pnpm setup (corepack or `pnpm/action-setup`, pinned to the image's 10.11.0) to the bug-fix `python-quality` CI job, so the real frozen pnpm install runs in CI. Or record the gap in TESTING.md. | `qa-engineer` / `developer` |
| OBS-189-01 | Update the Wave A roadmap row's `Issues/PRs` (#451, #453, #454 and, when merged, #458) and `What's missing` (S-189, S-190). | `planner` |

**Publication.** Per the caller's read-only constraint, this report is not committed and I posted nothing to #371 or #458. The caller (`planner`) is to post this header and verdict and a link on #371 and PR #458, and to confirm reviewers can reach it.

## 6. Reconciliation

Non-blocking: ran after the #458 merge. Confirmed by @llipe 2026-10-24 (`product-engineer`, `activity-drift-reconciliation`).

| Findings | Where they landed |
| -------- | ----------------- |
| DF-189-01 | This write-back: spec v2.6 §8.7 and §12 item 7, the D-62 amendment, stories v2.5 (S-189-AC3, S-193-AC3/AC6), test plan v2.4 (TC-189-18, TC-193-02) |
| DF-189-02, -03, -06 | Accepted as delivered |
| DF-189-04, -05, -08, -09 | Fixed in #458 (`211643b`, `17ee3be`); the gate items, reply phrases and makefile order are recorded in spec v2.6 §8.7 and the D-112 amendment |
| DF-189-07 | This write-back: stories v2.5, test plan v2.4, matrix v2.3, the D-62 amendment |

The S-189 fix-round hardening (work-tree walk, `.git` components, `fsckObjects`, tar caps, link-protection preflight) is recorded in spec v2.6 §8.7, §12 and §16, and in test plan v2.4 (TC-189-22, TC-189-23). Test plan §10.7 holds the full routing.

## Changelog

| Version | Date | Summary | Author |
| ------- | ---- | ------- | ------ |
| 1.1 | 2026-10-24 | Reconciliation section added: DF-189-01/04/05/07/08 and the fix-round hardening routed to spec v2.6, stories v2.5, test plan v2.4 and matrix v2.3; confirmed by @llipe 2026-10-24. | product-engineer |
| 1.0 | 2026-10-24 | Initial Audit Mode fidelity report for S-189 (#371), PR #458 @ `af142db`. | verifier |
