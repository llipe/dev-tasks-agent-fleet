"""
CodeQL scanner integration -- JS/TS + Python-only language dispatch and
two-phase CLI call (spec S4.3/S8.5, PRD S7.4a, requirements 14/17/51/58 row 5,
story S-132, issue #192).

Fifth and final concrete scanner -- follows `semgrep_runner.py`'s (S-128),
`gitleaks_runner.py`'s (S-129), `trivy_runner.py`'s (S-130), and
`checkov_runner.py`'s (S-131) `run_<tool>(workspace, timeout) -> ScanResult`
shape verbatim, importing `ScanResult`/`ScanStatus` from `scanners.types`
rather than redefining them.

**Blocking pre-check (task 8.0.1), resolved before this module was written:**
CodeQL CLI v2.27.0 ships a native `codeql-linux-arm64.zip` build
(`github/codeql-cli-binaries` release `v2.27.0`), and the same version's
bundle release (`github/codeql-action` tag `codeql-bundle-v2.27.0`) carries a
matching `codeql-bundle-linux-arm64.tar.gz` asset -- confirmed via the public
GitHub Releases API before any code in this module was written (PRD OQ5,
spec S15.2/S18 OQ1). The two query packs this module downloads
(`codeql/javascript-typescript-queries`, `codeql/python-queries`) are pure QL
source packs (`.ql`/`.qll` files + `qlpack.yml`), not platform-specific
binaries -- they carry no architecture restriction of their own; only the
CLI that compiles/runs them needs a native build, which v2.27.0 has. CodeQL
CLI is pinned at **v2.27.0** in the Dockerfile (S8.1/S15.2).

Per PRD S7.4a / spec S8.5's own prose (not its two-line `run_codeql(...) ->
ScanResult` stub, which is silent on internal shape): CodeQL is scoped to
exactly two query packs -- `javascript-typescript` and `python` -- with
**no third branch**. A repository matching neither trigger is `SKIPPED`
(requirement 17/51), not failed; a repository matching both runs CodeQL
twice (once per language), and both languages' findings are merged into one
`ScanResult` (requirement 51/8.9). Because both packs are interpreted-
language extraction (no compiled-language pack ships in this image --
requirement 51), `codeql database create` never triggers a compiled build
step in v1 (requirement 14) -- there is no JDK/Go toolchain/C-C++ compiler in
this image for it to invoke even if it wanted to.

**Two-phase CLI call, per language:** `codeql database create
--language=<lang> --source-root=<workspace> <db-path>` followed by `codeql
database analyze <db-path> <query-pack> --format=sarif-latest --output=...`
(spec S4.3's sequence diagram, S15.2's Dockerfile snippet). Both phases are
run under `timeout` **independently** (each its own full budget, not a
split shared envelope) -- the same "no shared budget split across multiple
attempted sub-calls" convention `trivy_runner.py`'s three-mode dispatch and
`checkov_runner.py`'s single call already establish, generalized here to
two phases per language, per-language (so up to 4 subprocess calls total in
the both-languages case, each independently bounded).

**Deviation 1 -- `--output=/dev/stdout`, not a real output file, mirroring
`gitleaks_runner.py`'s identical fix (S-129).** CodeQL's real `database
analyze` CLI has no "print SARIF to stdout" mode -- `--output` is a
mandatory file-path flag. Rather than introduce a temp-file-then-read
lifecycle unique to this one scanner module (every other `run_<tool>()`,
including this one's own `database create` phase, reads/inspects
`proc.stdout`/`proc.returncode` directly with no side-effect file to manage
across a mock boundary), this module points `--output` at `/dev/stdout` --
the same Linux-device-file trick `gitleaks_runner.py`'s module docstring
documents and justifies (AgentCore Runtime's container target is Linux,
PRD S12.3/`agentcore.json`). This keeps `_run_language()`'s analyze phase
byte-for-byte structurally identical to every sibling scanner's
subprocess-capture-then-normalize pattern, which S-135's `run_scanners()`
dispatcher relies on being uniform. Flagged per this story's pre-authorized
"apply proactively" instruction -- same class of decision as
`gitleaks_runner.py`'s own identical fix.

**Deviation 2 -- `security-severity` lives on the SARIF *rule* definition,
not the result.** A literal reading of `severity_from_codeql()`'s own
docstring ("SARIF `results[].properties.security-severity`") describes
where the *value* conceptually comes from, but real CodeQL SARIF output
places `security-severity` (and CWE `tags`) on each rule's own definition
object, `runs[].tool.driver.rules[].properties.security-severity` -- a
*string* (e.g. `"9.3"`), not a float -- looked up per-result via that
result's `ruleId` (falling back to `results[].rule.index` into the same
`rules` array when `ruleId` is absent, CodeQL's own documented alternate
addressing mode). `normalize_codeql()` below builds that rule lookup once
per SARIF `run` and reads `security-severity`/`tags` through it; a result's
own `properties` bag is checked first as a defensive belt-and-braces
fallback (SARIF technically permits either placement), but real CodeQL
output only ever populates the rule-level one. This is the same class of
pre-authorized "apply proactively" correctness fix as `trivy_runner.py`'s
`Class`-field branching and `checkov_runner.py`'s dual-shape acceptance --
built from CodeQL's actual documented SARIF output shape, not from a
literal, underspecified reading of the severity function's own docstring.
`severity_from_codeql()` itself (S-126, already merged) is imported and
called verbatim -- only the *lookup* of its two arguments is this module's
concern, never its threshold logic.

**Deviation 3 -- non-zero exit code IS treated as failure here, unlike the
other four scanners.** `run_semgrep()`/`run_gitleaks()`/`run_trivy()` all
deliberately ignore `proc.returncode` (Gitleaks in particular exits
non-zero on a *successful*, findings-bearing run unless neutralized with
its own `--exit-code 0` flag). CodeQL's CLI has the opposite, more
conventional convention: both `database create` and `database analyze`
exit `0` on genuine success (findings present or not) and non-zero only on
a real failure (e.g. "no source code was seen during the build" when the
language extractor finds nothing to analyze despite this module's own
trigger heuristic having matched, or a corrupted/incompatible database).
Checking `returncode` here is therefore not an inconsistency with the other
four modules' pattern but the correct application of the same underlying
principle (treat a tool's own success/failure signal as authoritative) to a
tool whose signal happens to be conventional rather than inverted.

**Deviation 4 -- one-language-fails-the-other-succeeds is all-or-nothing,
mirroring `trivy_runner.py`'s Deviation 1.** When both languages trigger and
one language's two-phase call fails (crash/timeout/non-zero exit/
unparseable SARIF) while the other succeeds, the aggregate `ScanResult` is
`ScanStatus.FAILED` with `findings=[]` and a `reason` naming the failed
language -- the successfully-scanned language's findings are not returned
alongside a `FAILED` status. This keeps CodeQL's own success/failure
semantics as unambiguous as the other four scanners' (never a partial-success
status), the same trade-off `trivy_runner.py`'s three-mode aggregation
already makes and documents. `run_scanners()` (S-135) treats a `FAILED`
CodeQL result as one tool's `error`-level event, non-fatal to the overall
run (PRD requirement 18, exercised by test plan SC-34).

**`remediation.kind` -- always `"structural"`, never `None` and never
`"version_bump"`/`"semgrep_autofix"`.** CodeQL has no native mechanical fix
path (no autofix patch, no version to bump) -- spec S8.4's own `classify()`
pseudocode comment explicitly groups CodeQL alongside Checkov in the
structural-remediation default branch ("`# structural remediation,
checkov/codeql/gitleaks default`"). This module follows that comment's
explicit example rather than leaving `remediation=None` (which would
route to `Bucket.UNSCANNABLE` instead, a materially different outcome
`classifier.py`, S-134, is not this story's scope to adjudicate further --
`checkov_runner.py`'s identical unconditional-`"structural"` choice is
this module's direct precedent).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from normalize import Finding, Remediation
from scanners.types import ScanResult, ScanStatus
from severity import severity_from_codeql

TOOL_NAME = "codeql"

# PRD S7.4a -- exactly these two entries, no third branch. Order here is the
# canonical dispatch order whenever both languages trigger (JS/TS before
# Python), so `raw_ref` numbering and subprocess-call order are deterministic
# across runs, not dependent on filesystem walk ordering.
_QUERY_PACKS: dict[str, str] = {
    "javascript-typescript": "codeql/javascript-typescript-queries",
    "python": "codeql/python-queries",
}

_JS_TS_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx"}
_JS_TS_MARKER_FILES = {"package.json"}
_PY_EXTENSIONS = {".py"}
_PY_MARKER_FILES = {"pyproject.toml", "requirements.txt"}

# Vendored/VCS/venv content must never trip either trigger -- mirrors
# `checkov_runner.py`'s identical `_SKIP_DIRS` rationale (a dependency's own
# bundled fixtures or the agent's own virtualenv must not cause a false
# "this repo has JS/TS" or "this repo has Python" detection).
_SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".terraform",
}


def detect_languages(workspace: Path) -> list[str]:
    """Best-effort detection of which of the two supported CodeQL languages
    (module docstring; PRD S7.4a) `workspace` contains, in canonical dispatch
    order (`["javascript-typescript", "python"]`, filtered to only the
    languages actually detected). Returns `[]` when neither trigger matches
    (the requirement 17/51 skip condition) -- never raises.

    JS/TS triggers on any `.js`/`.jsx`/`.ts`/`.tsx` file or a `package.json`
    anywhere in the tree; Python triggers on any `.py` file or a
    `pyproject.toml`/`requirements.txt`. Stops walking as soon as both have
    been found (no need to keep scanning once the maximal dispatch set is
    already known).
    """
    found_js_ts = False
    found_python = False

    for _root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in files:
            suffix = Path(name).suffix
            if not found_js_ts and (suffix in _JS_TS_EXTENSIONS or name in _JS_TS_MARKER_FILES):
                found_js_ts = True
            if not found_python and (suffix in _PY_EXTENSIONS or name in _PY_MARKER_FILES):
                found_python = True
        if found_js_ts and found_python:
            break

    languages: list[str] = []
    if found_js_ts:
        languages.append("javascript-typescript")
    if found_python:
        languages.append("python")
    return languages


def _build_create_command(workspace: Path, db_path: Path, language: str) -> list[str]:
    return [
        "codeql",
        "database",
        "create",
        str(db_path),
        f"--language={language}",
        f"--source-root={workspace}",
        "--overwrite",
    ]


def _build_analyze_command(db_path: Path, language: str) -> list[str]:
    # See module docstring Deviation 1 -- /dev/stdout stands in for a native
    # stdout-output mode CodeQL's real CLI does not have.
    return [
        "codeql",
        "database",
        "analyze",
        str(db_path),
        _QUERY_PACKS[language],
        "--format=sarif-latest",
        "--output=/dev/stdout",
        "--threads=0",
    ]


def _rule_lookup(run: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Build the `ruleId -> rule definition` lookup for one SARIF `run`
    object (module docstring Deviation 2), plus the raw `rules` list (kept
    around for the `results[].rule.index` fallback-addressing mode).
    """
    driver = (run.get("tool") or {}).get("driver") or {}
    rules: list[dict[str, Any]] = driver.get("rules") or []
    by_id = {rule["id"]: rule for rule in rules if "id" in rule}
    return by_id, rules


def _resolve_rule(
    result: dict[str, Any], rules_by_id: dict[str, dict[str, Any]], rules: list[dict[str, Any]]
) -> dict[str, Any]:
    """Resolve a `results[]` entry's rule definition -- by `ruleId` first,
    falling back to `rule.index` addressing (both are valid SARIF, CodeQL's
    own output uses `ruleId` in practice but the index form is documented
    and this module accepts it defensively). Returns `{}` when neither
    resolves to a real rule (never raises -- a missing rule definition just
    means no `security-severity`/`tags` signal is available, degrading to
    `severity_from_codeql()`'s own unknown-severity floor).
    """
    rule_id = result.get("ruleId")
    if rule_id is not None and rule_id in rules_by_id:
        return rules_by_id[rule_id]
    rule_ref = result.get("rule") or {}
    index = rule_ref.get("index")
    if isinstance(index, int) and 0 <= index < len(rules):
        return rules[index]
    return {}


def _security_severity(result: dict[str, Any], rule: dict[str, Any]) -> float | None:
    """`security-severity` resolution (module docstring Deviation 2):
    result-level `properties` checked first (defensive, SARIF technically
    permits it there), then the rule-level `properties` where CodeQL's real
    output actually places it. Returns `None` when neither carries the
    field -- `severity_from_codeql()`'s `level` fallback then applies.
    """
    result_props = result.get("properties") or {}
    rule_props = rule.get("properties") or {}
    raw = result_props.get("security-severity", rule_props.get("security-severity"))
    if raw is None:
        return None
    return float(raw)


def _resolve_level(result: dict[str, Any], rule: dict[str, Any]) -> str | None:
    """SARIF `level` resolution: the result's own `level` when present,
    else the rule's `defaultConfiguration.level` (SARIF's own documented
    fallback for an omitted per-result level). `None` when neither is
    present -- `severity_from_codeql()`'s shared unknown-severity floor
    then applies.
    """
    level = result.get("level")
    if level is not None:
        return level
    default_config = rule.get("defaultConfiguration") or {}
    return default_config.get("level")


def _cwe_or_category(rule_id: str | None, rule: dict[str, Any]) -> str:
    """First `external/cwe/cwe-<n>` tag from the rule's `properties.tags`
    (CodeQL's own documented convention for surfacing CWE metadata in
    SARIF), rendered as `CWE-<n>`. Falls back to `rule_id`, mirroring every
    other scanner module's identical last-resort fallback (so the
    cross-tool dedup key, `fingerprint()`'s `rule_id or cwe_or_category`, is
    never empty) -- and finally to a fixed placeholder in the pathological
    case where even `rule_id` is absent from the SARIF result.
    """
    rule_props = rule.get("properties") or {}
    tags = rule_props.get("tags") or []
    for tag in tags:
        if isinstance(tag, str) and tag.lower().startswith("external/cwe/"):
            cwe_id = tag.rsplit("/", maxsplit=1)[-1]
            return cwe_id.upper()
    return rule_id or "codeql-unknown"


def _location(result: dict[str, Any]) -> tuple[str, int, int]:
    """`(file_path, line_start, line_end)` from a result's first
    `locations[]` entry. `endLine` is absent on SARIF's own single-line
    shorthand (a single-line result need not repeat `startLine` as
    `endLine`) -- defaults to `startLine` in that case, not `1`, so a
    single-line CodeQL result's line range is never silently widened to a
    placeholder. A result with no `locations[]` at all (SARIF permits this
    for whole-file-scope results) falls back to an empty `file_path` and
    `(1, 1)`, mirroring every other scanner's `(1, 1)` placeholder for
    "no native per-line location" cases.
    """
    locations = result.get("locations") or []
    if not locations:
        return "", 1, 1
    physical = locations[0].get("physicalLocation") or {}
    uri = (physical.get("artifactLocation") or {}).get("uri", "")
    region = physical.get("region") or {}
    line_start = region.get("startLine", 1)
    line_end = region.get("endLine", line_start)
    return uri, line_start, line_end


def normalize_codeql(raw_output: str, language: str) -> list[Finding]:
    """Parse one CodeQL `--format=sarif-latest` payload (one language's
    `database analyze` output) into `Finding` records (spec S8.1/S8.1a, PRD
    requirement 58 row 5).

    ``language`` (``"javascript-typescript"`` | ``"python"``) is used only to
    prefix `raw_ref` so findings combined from `run_codeql()`'s up-to-two
    subprocess-call-pairs (each its own raw SARIF artifact) never collide --
    it plays no role in severity/CWE resolution, which is driven entirely by
    each result's own rule definition (module docstring Deviation 2).

    Pure function over the raw JSON text. A SARIF document with an empty (or
    absent) `runs[].results` array normalizes to `[]` -- CodeQL's own
    "nothing found" shape, no special-cased `null` handling needed (unlike
    Gitleaks/Trivy/Checkov, real SARIF always writes `"results": []`, never
    `null`, when a run analyzed the tree and found nothing). Raises
    `json.JSONDecodeError` on invalid JSON and `KeyError`/`TypeError` on a
    structurally-unexpected payload (missing `runs` key entirely, or a
    `runs` entry that is not a mapping) -- `_run_language()` below catches
    both and maps them to the non-fatal `ScanStatus.FAILED` path (PRD
    requirement 18); this function itself stays a strict,
    total-over-its-documented-input-shape parser rather than silently
    swallowing structural errors.

    `remediation.kind = "structural"` unconditionally (module docstring) --
    CodeQL has no native mechanical fix path in v1.
    """
    data = json.loads(raw_output)
    runs = data["runs"]

    findings: list[Finding] = []
    index = 0
    for run in runs:
        rules_by_id, rules = _rule_lookup(run)
        results = run.get("results") or []
        for result in results:
            rule_id = result.get("ruleId")
            rule = _resolve_rule(result, rules_by_id, rules)

            security_severity = _security_severity(result, rule)
            level = _resolve_level(result, rule)

            file_path, line_start, line_end = _location(result)
            message = ((result.get("message") or {}).get("text")) or rule_id or "codeql finding"

            findings.append(
                Finding(
                    tool=TOOL_NAME,
                    rule_id=rule_id or "unknown",
                    severity=severity_from_codeql(security_severity, level),
                    file_path=file_path,
                    line_start=line_start,
                    line_end=line_end,
                    message=message,
                    cwe_or_category=_cwe_or_category(rule_id, rule),
                    remediation=Remediation(
                        kind="structural", patch=None, target_version=None, lockfile_managed=False
                    ),
                    raw_ref=f"{TOOL_NAME}:{language}#{index}",
                )
            )
            index += 1

    return findings


def _run_language(workspace: Path, language: str, timeout: int) -> tuple[list[Finding], str | None]:
    """Run one language's two-phase CodeQL call (module docstring) and
    normalize its SARIF output. Returns ``(findings, error_reason)`` --
    ``error_reason`` is `None` on success, populated (and ``findings`` is
    ``[]``) on a crash-to-start (`OSError`), a timeout
    (`subprocess.TimeoutExpired`), a non-zero exit from either phase (module
    docstring Deviation 3), or unparseable/structurally-unexpected SARIF
    from the analyze phase.

    A fresh, per-call temporary directory holds the CodeQL database -- never
    reused across languages or calls, so a `python` database build cannot
    contaminate (or be contaminated by) a `javascript-typescript` one when
    both run in the same `run_codeql()` invocation.
    """
    with tempfile.TemporaryDirectory(prefix="codeql-db-") as tmp:
        db_path = Path(tmp) / f"db-{language}"

        create_cmd = _build_create_command(workspace, db_path, language)
        try:
            create_proc = subprocess.run(
                create_cmd, capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            return [], f"codeql database create ({language}) timed out after {timeout}s"
        except OSError as exc:
            return [], f"codeql database create ({language}) failed to start: {exc}"
        if create_proc.returncode != 0:
            return [], (
                f"codeql database create ({language}) exited {create_proc.returncode}: "
                f"{create_proc.stderr.strip()[:300]}"
            )

        analyze_cmd = _build_analyze_command(db_path, language)
        try:
            analyze_proc = subprocess.run(
                analyze_cmd, capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            return [], f"codeql database analyze ({language}) timed out after {timeout}s"
        except OSError as exc:
            return [], f"codeql database analyze ({language}) failed to start: {exc}"
        if analyze_proc.returncode != 0:
            return [], (
                f"codeql database analyze ({language}) exited {analyze_proc.returncode}: "
                f"{analyze_proc.stderr.strip()[:300]}"
            )

        try:
            findings = normalize_codeql(analyze_proc.stdout, language=language)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            return [], f"unparseable codeql ({language}) SARIF output: {exc}"

        return findings, None


def run_codeql(workspace: Path, timeout: int) -> ScanResult:
    """Run CodeQL against `workspace` and normalize its combined output into
    one `ScanResult` (spec S4.3/S8.5, PRD requirements 14/17/51, story S-132
    AC bullets; see module docstring for the two-phase-per-language shape and
    all four documented deviations).

    Pre-flight: `detect_languages(workspace)` decides dispatch. Empty ->
    `ScanStatus.SKIPPED` with a named `reason` (requirement 17/51) and no
    subprocess call made at all -- the canonical "repository matching
    neither language" outcome (PRD AC24 groundwork, test plan SC-42). One
    language -> that language's two-phase call runs once. Both -> both
    languages' two-phase calls run (in canonical `["javascript-typescript",
    "python"]` order), and their findings are merged into one `ScanResult`
    (test plan SC-41) -- never double-counted, each language's own SARIF
    `run` contributes its own independently-indexed `raw_ref` set.

    Each attempted language's two subprocess calls are bounded independently
    by `timeout` (PRD requirement 19 -- callers pass `config.SCANNER_TIMEOUT`,
    no shared budget is split across the up-to-four calls in the
    both-languages case). If *any attempted* language's two-phase call
    crashes, times out, exits non-zero, or produces unparseable SARIF, the
    aggregate `ScanResult.status` is `ScanStatus.FAILED` (PRD requirement 18)
    with `findings=[]` and a `reason` naming every failed language (module
    docstring Deviation 4, test plan SC-34) -- a language that is never
    attempted (the other-language-only case) is not counted as a failure.
    Never raises: every real/mocked subprocess failure path is caught inside
    `_run_language()`.
    """
    languages = detect_languages(workspace)
    if not languages:
        return ScanResult(
            tool=TOOL_NAME,
            status=ScanStatus.SKIPPED,
            findings=[],
            reason=(
                "no JS/TS or Python content detected (no .js/.jsx/.ts/.tsx/package.json "
                "or .py/pyproject.toml/requirements.txt found)"
            ),
        )

    all_findings: list[Finding] = []
    errors: list[str] = []
    for language in languages:
        findings, error = _run_language(workspace, language, timeout)
        if error is not None:
            errors.append(error)
        else:
            all_findings.extend(findings)

    if errors:
        return ScanResult(
            tool=TOOL_NAME,
            status=ScanStatus.FAILED,
            findings=[],
            reason="; ".join(errors),
        )

    return ScanResult(tool=TOOL_NAME, status=ScanStatus.PASSED, findings=all_findings, reason=None)
