"""
Semgrep scanner integration (spec §8.5, PRD §7.4a/§7.4b, story S-128).

First concrete scanner -- establishes the `run_<tool>(workspace, timeout) ->
ScanResult` shape (`scanners.types`) that every later scanner module
(S-129 Gitleaks, S-130 Trivy, S-131 Checkov, S-132 CodeQL) follows verbatim.

Deviation from spec §8.6's literal `apply_semgrep_autofix` pseudocode
(`["semgrep", "--autofix", "--config", RULESET, str(workspace)]`, which
passes `RULESET` as a single space-joined string to one `--config` flag):
that is not valid Semgrep CLI syntax -- `--config` accepts exactly one
registry id or path per flag; a value containing a literal space is passed
to the child process as one argv entry (no shell involved,
`subprocess.run` does not word-split it) and Semgrep would fail to resolve
it as any known ruleset. `RULESET` here is a tuple of the four individual
pinned registry ids (PRD requirement 52); `_build_command()` below emits one
`--config <id>` pair per entry. Flagged as the same class of literal
spec-pseudocode defect the S-126/S-127 fidelity audits caught in
`severity.py` (dict-indexing `KeyError`) -- fixed here, not replicated, per
this story's pre-authorized "apply proactively" instruction. The S-136
autofix fixer (which reuses this same `RULESET` constant per the spec's own
cross-reference) inherits the fix automatically by importing the tuple
rather than re-deriving a joined string.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from normalize import Finding, Remediation
from scanners.types import ScanResult, ScanStatus
from severity import severity_from_semgrep

TOOL_NAME = "semgrep"

# PRD requirement 52 -- pinned rulesets only, never `--config auto` (an
# always-latest, unpinned registry alias that would make scan results
# non-reproducible run-to-run and outside this agent's change-control
# story). Reused verbatim by the S-136 autofix fixer (spec §8.6).
RULESET: tuple[str, ...] = ("p/javascript", "p/typescript", "p/python", "p/security-audit")


def _build_command(workspace: Path) -> list[str]:
    """Build the `semgrep --json --config <id> [--config <id> ...] <workspace>`
    invocation -- one `--config` flag per `RULESET` entry (see module
    docstring for why this is not a single joined-string `--config` value).
    """
    cmd = ["semgrep", "--json"]
    for ruleset_id in RULESET:
        cmd.extend(["--config", ruleset_id])
    cmd.append(str(workspace))
    return cmd


def _extract_cwe_or_category(metadata: dict[str, Any], rule_id: str) -> str:
    """Derive the cross-tool dedup category key (spec §8.3 groups on
    `(file_path, cwe_or_category)`) from a Semgrep result's `extra.metadata`.

    Preference order: `metadata.cwe` (list or bare string; the leading
    `CWE-<n>` token is extracted from Semgrep's `"CWE-95: <description>"`
    convention -- a bare id, which `run_scanners()` then canonicalizes to
    `CWE-<int>` alongside every other tool's value; S-141 found CodeQL emits
    a zero-padded `CWE-079` at the normalizer level, so per-normalizer
    uniformity is NOT assumed anymore) -> `metadata.owasp` (first entry, used
    verbatim -- there is no equivalent bare-id convention to extract) ->
    `rule_id` (Semgrep's own `check_id`) as the last-resort fallback, so
    `cwe_or_category` is never empty (this module never returns `""`, which
    matters for `fingerprint()`'s `rule_id or cwe_or_category` fallback --
    EC-35 -- since `rule_id` is always non-empty for Semgrep findings, this
    fallback chain is a dedup-quality concern here, not a fingerprint
    correctness one).
    """
    cwe = metadata.get("cwe")
    if cwe:
        raw = cwe[0] if isinstance(cwe, list) else cwe
        head = raw.split(":", 1)[0].strip()
        return head if head.upper().startswith("CWE-") else raw
    owasp = metadata.get("owasp")
    if owasp:
        return owasp[0] if isinstance(owasp, list) else owasp
    return rule_id


def normalize_semgrep(raw_output: str) -> list[Finding]:
    """Parse Semgrep `--json` output into `Finding` records (spec §8.1).

    Pure function over the raw JSON text. Raises `json.JSONDecodeError` on
    invalid JSON and `KeyError`/`TypeError` on a structurally-unexpected
    payload (missing `results`, or a result missing a required field) --
    `run_semgrep()` below catches both and maps them to the non-fatal
    `ScanStatus.FAILED` path (PRD requirement 18); this function itself
    stays a strict, total-over-its-documented-input-shape parser rather than
    silently swallowing structural errors.

    `remediation` is `None` (not a `Remediation(kind="none", ...)` value)
    when the rule carries no native autofix patch: `Remediation.kind` is
    typed `str` (`normalize.py`), not `str | None`, so "no mechanical fix
    known yet" is represented at the `Finding.remediation` field itself,
    consistent with `normalize.py`'s own docstring ("`None` for an
    unscannable candidate"). A present-but-empty `extra.fix` string (the
    edge-case matrix's "autofix patch present but malformed") is treated
    identically to an absent one -- an empty string is not a usable patch.
    """
    data = json.loads(raw_output)
    results = data["results"]

    findings: list[Finding] = []
    for index, result in enumerate(results):
        extra = result.get("extra", {})
        metadata = extra.get("metadata", {})
        rule_id = result["check_id"]

        fix = extra.get("fix") or None
        remediation = (
            Remediation(
                kind="semgrep_autofix", patch=fix, target_version=None, lockfile_managed=False
            )
            if fix
            else None
        )

        findings.append(
            Finding(
                tool=TOOL_NAME,
                rule_id=rule_id,
                severity=severity_from_semgrep(extra.get("severity", "")),
                file_path=result["path"],
                line_start=result["start"]["line"],
                line_end=result["end"]["line"],
                message=extra.get("message", ""),
                cwe_or_category=_extract_cwe_or_category(metadata, rule_id),
                remediation=remediation,
                raw_ref=f"{TOOL_NAME}#{index}",
            )
        )
    return findings


def run_semgrep(workspace: Path, timeout: int) -> ScanResult:
    """Run Semgrep against `workspace` and normalize its output (spec §8.5).

    Enforces `timeout` independently of any other scanner (PRD requirement
    19 -- callers pass `config.SCANNER_TIMEOUT`, no shared timeout budget is
    read from here). A crash-to-start (`OSError` -- e.g. the `semgrep`
    binary missing from the image), a timeout (`subprocess.TimeoutExpired`),
    or unparseable/structurally-unexpected stdout are all non-fatal to the
    overall run (PRD requirement 18): each maps to `ScanStatus.FAILED` with
    `findings=[]` and a `reason` describing what happened, never an
    exception raised out of this function.

    Deliberately does NOT treat a non-zero exit code alone as a failure:
    Semgrep exits `1` whenever findings are present (not an error), so
    `subprocess.run` is called without `check=True` and success/failure is
    decided purely by whether stdout parses into the expected shape.

    No secrets list is threaded through this call (the spec §8.5 `run_<tool>`
    signature takes only `workspace`/`timeout`) -- `scrubber.scrub_process_error()`
    is applied at the orchestration layer (S-135's `run_scanners()`), once a
    per-run secrets list is available, before any per-tool `reason` string
    reaches a log, artifact, or PR body.
    """
    cmd = _build_command(workspace)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return ScanResult(
            tool=TOOL_NAME,
            status=ScanStatus.FAILED,
            findings=[],
            reason=f"semgrep timed out after {timeout}s",
        )
    except OSError as exc:
        return ScanResult(
            tool=TOOL_NAME,
            status=ScanStatus.FAILED,
            findings=[],
            reason=f"semgrep failed to start: {exc}",
        )

    try:
        findings = normalize_semgrep(proc.stdout)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        return ScanResult(
            tool=TOOL_NAME,
            status=ScanStatus.FAILED,
            findings=[],
            reason=f"unparseable semgrep output: {exc}",
        )

    return ScanResult(tool=TOOL_NAME, status=ScanStatus.PASSED, findings=findings, reason=None)
