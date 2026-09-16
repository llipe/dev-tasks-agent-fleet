"""
Trivy scanner integration -- `fs`/`config`/`image` three-mode dispatch and
the D24/requirement 54 `lockfile_managed` boundary (spec §8.1/§8.4/§8.5,
PRD requirements 16/17/53/54, story S-130).

The single most consequential normalizer in this agent: `lockfile_managed`
(set here, on `Remediation`) is what `classifier.py` (S-134) branches on to
decide whether a Trivy version-bump finding is this agent's own to fix
(`Bucket.MECHANICAL`) or belongs to the sibling `dependency-update` agent's
lane (`Bucket.MANUAL`, D24). Per spec §8.4's own design note: "`lockfile_managed`
is set by `trivy_runner.py`'s normalizer, not inferred [in the classifier] --
it inspects Trivy's own target-file field against `_JS_LOCKFILES` only ...
at parse time, keeping the classifier itself free of scanner-specific
parsing." `_JS_LOCKFILES` therefore lives here (the authoritative copy),
not duplicated in `classifier.py` -- the classifier only ever consumes the
resulting `bool` field.

Third concrete scanner -- follows `semgrep_runner.py`'s (S-128) and
`gitleaks_runner.py`'s (S-129) `run_<tool>(workspace, timeout) -> ScanResult`
shape, importing `ScanResult`/`ScanStatus` from `scanners.types` rather than
redefining them. Diverges from those two modules in one structural way this
module's docstring calls out explicitly below: Trivy is invoked as *three*
independent subprocess calls (`fs`, `config`, conditional `image`), not one,
so `run_trivy()` aggregates three attempts into a single `ScanResult`.

**Deviation 1 -- three-mode aggregation, not spec §8.5's implied single call.**
Spec §8.5 shows `run_trivy(workspace, timeout) -> ScanResult` with the same
single-call signature as every other scanner, but PRD requirement 16 and this
story's own acceptance criteria require Trivy's `fs`, `config`, and
conditional `image` modes all to run and contribute findings to one combined
result -- Trivy's real CLI has no single invocation that does all three at
once. `run_trivy()` below runs up to three independent `subprocess.run()`
calls (`_run_mode()` per call), each with its own `timeout` budget (so one
slow mode cannot silently consume the whole step's share of the caller's
overall `SCANNER_TIMEOUT` allotment across all three), and combines their
findings into one `ScanResult`. If *any attempted* mode crashes, times out,
or produces unparseable output, the aggregate status is `ScanStatus.FAILED`
(PRD requirement 18) with a `reason` naming which mode(s) failed -- a mode
that is never attempted (image mode with no Dockerfile) is not counted as a
failure. This is the same class of pre-authorized "apply proactively"
correctness fix as `semgrep_runner.py`'s `RULESET` tuple-vs-joined-string fix
and `gitleaks_runner.py`'s `/dev/stdout` report-path fix.

**Deviation 2 -- `image` mode targets a representative base image, not the
built image.** PRD requirement 16 says `image` mode runs "when a Dockerfile
is present, against a representative base image" (issue #190's own technical
note flags this ambiguity and asks this story to resolve it to a concrete
choice). Building the repository's actual image is a separate, heavier
concern outside a scan-only step's scope (no Docker daemon is assumed to be
available in the scanner sandbox). This module resolves "representative
base image" to: parse the workspace's `Dockerfile` for its first `FROM`
instruction (the base of the first build stage in a multi-stage build,
ignoring any `AS <alias>` suffix) and run `trivy image <that reference>`
against it directly, pulling from the registry rather than a locally built
tag. This is the concrete v1 choice this story's technical notes ask to be
recorded. When no Dockerfile exists, or a Dockerfile exists but carries no
parseable `FROM` line, `image` mode is skipped entirely (no subprocess call
is made) -- not failed (PRD requirement 17); the aggregate `ScanResult` still
reflects `PASSED`/`FAILED` based on `fs`/`config` alone.

**Deviation 3 -- remediation kind is driven by Trivy's own `Class` field, not
by which subprocess mode produced the payload.** A literal reading of this
story's own acceptance criteria ("`config`/`image` findings normalize with
`remediation.kind = "structural"` or `None` as appropriate") groups `image`
mode with `config` mode as structural. That reading is inconsistent with
spec §8.4's own classifier walkthrough, which requires a *reachable*
`mechanical` branch for "Trivy finding on a container base image (non-lockfile)
... clean version-bump" (PRD AC10) -- a base-image OS-package vulnerability
finding IS a `Vulnerabilities`-class result, structurally identical to an
`fs`-mode dependency vulnerability, and Trivy always reports it with a
`FixedVersion` field, never a `Misconfigurations`-shaped one. Treating every
`image`-mode finding as `structural` would make AC10 permanently
unreachable. `normalize_trivy()` below therefore branches on each `Result`
entry's own `Class` field (`"config"` -> `Misconfigurations`, everything else
-- `"lang-pkgs"`/`"os-pkgs"` -- -> `Vulnerabilities`), which is the actual
signal Trivy's real JSON output carries for this distinction, regardless of
which CLI subcommand (`fs`/`config`/`image`) produced the payload. Genuine
`Misconfigurations`-class results (Class == "config") are always
`structural`, matching the AC's intent for the tool's IaC-scanning half.
Flagged per this story's pre-authorized "apply proactively" instruction, same
class of decision as `severity.py`'s S-126 fidelity-audit fixes.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from normalize import Finding, Remediation
from scanners.types import ScanResult, ScanStatus
from severity import severity_from_trivy

TOOL_NAME = "trivy"

# D24 / PRD requirement 54 -- ONLY these two files route a Trivy version-bump
# finding into `dependency-update`'s lane (`classifier.py`'s `Bucket.MANUAL`,
# S-134). Python manifests (`requirements.txt`, `poetry.lock`, `Pipfile.lock`)
# are deliberately absent -- `dependency-update` has no Python support (its
# own PRD lists pip/uv as deferred), so a Python version-bump finding has
# nothing to collide with and must stay eligible for `Bucket.MECHANICAL`.
# This is the authoritative definition (spec §8.4's own classifier pseudocode
# shows an identically-named constant, but its accompanying prose clarifies
# that the real decision is made here, at parse time -- see module
# docstring); `classifier.py` never redefines or re-derives this set, it only
# reads the resulting `Remediation.lockfile_managed` boolean.
_JS_LOCKFILES: frozenset[str] = frozenset({"package-lock.json", "pnpm-lock.yaml"})

_FROM_LINE_RE = re.compile(r"^\s*FROM\s+(\S+)", re.IGNORECASE)


def _first_base_image(workspace: Path) -> str | None:
    """Parse `workspace/Dockerfile` for its first `FROM` instruction's image
    reference (see module docstring Deviation 2). Returns `None` when no
    `Dockerfile` exists or it contains no parseable `FROM` line -- both
    non-fatal, `image` mode is simply skipped by the caller.
    """
    dockerfile = workspace / "Dockerfile"
    if not dockerfile.is_file():
        return None
    for line in dockerfile.read_text().splitlines():
        match = _FROM_LINE_RE.match(line)
        if match:
            return match.group(1)
    return None


def _build_fs_command(workspace: Path) -> list[str]:
    return ["trivy", "fs", "--format", "json", "--scanners", "vuln", str(workspace)]


def _build_config_command(workspace: Path) -> list[str]:
    return ["trivy", "config", "--format", "json", str(workspace)]


def _build_image_command(image_ref: str) -> list[str]:
    return ["trivy", "image", "--format", "json", image_ref]


def _parse_version_tuple(raw: str) -> tuple[int, ...] | None:
    """Best-effort leading-numeric-dotted-group parse (e.g. ``"2.36-9+deb12u4"``
    -> ``(2, 36)``). Deliberately not a full semver parser (`eligibility.py`'s
    `parse_semver` in the sibling agent is stricter and is `classifier.py`'s
    concern, not this normalizer's) -- Trivy's own `FixedVersion` candidates
    span npm/pip semver, Debian/RPM package-version syntax, and other
    ecosystem-specific formats, so this only needs to be good enough to order
    the (typically 1-2) candidates Trivy itself proposes as fix targets for
    the *same* package. Returns `None` when no leading numeric group is
    found at all.
    """
    match = re.match(r"^\D*(\d+)(?:\.(\d+))?(?:\.(\d+))?", raw)
    if not match:
        return None
    return tuple(int(g) for g in match.groups() if g is not None)


def _lowest_fixed_version(raw_fixed_version: str) -> str | None:
    """Trivy's `FixedVersion` field is sometimes a single version and
    sometimes a comma-separated list of versions closing the advisory on
    different release branches (e.g. ``"4.17.21, 4.18.0"``). PRD requirement
    53's issue text calls for "the lowest closing version" -- this picks the
    numerically-lowest parseable candidate, falling back to the first listed
    candidate verbatim when none parse (still a valid, Trivy-endorsed fix
    target, just not orderable by this simplified parser). Returns `None`
    when the field is absent or empty (no fix published yet).
    """
    stripped = (raw_fixed_version or "").strip()
    if not stripped:
        return None
    candidates = [c.strip() for c in stripped.split(",") if c.strip()]
    if not candidates:
        return None
    parseable = [(v, c) for c in candidates if (v := _parse_version_tuple(c)) is not None]
    if parseable:
        parseable.sort(key=lambda pair: pair[0])
        return parseable[0][1]
    return candidates[0]


def _is_js_lockfile(target: str) -> bool:
    """The D24/req 54 boundary check -- basename membership in
    `_JS_LOCKFILES`, not full-path equality, so a nested monorepo path
    (e.g. ``"frontend/pnpm-lock.yaml"``) is still correctly recognized.
    """
    return Path(target).name in _JS_LOCKFILES


def _normalize_vulnerability(vuln: dict[str, Any], target: str, mode: str, index: int) -> Finding:
    rule_id = vuln["VulnerabilityID"]
    fixed_version = _lowest_fixed_version(vuln.get("FixedVersion", ""))

    remediation = (
        Remediation(
            kind="version_bump",
            patch=None,
            target_version=fixed_version,
            # D24/req 54 boundary -- decided here, once, at parse time (see
            # module + `_JS_LOCKFILES` docstrings). Applies identically to
            # npm/pnpm and Python findings; the split is enforced later, at
            # classification (`classifier.py`, S-134), never here.
            lockfile_managed=_is_js_lockfile(target),
        )
        if fixed_version is not None
        else None
    )

    cwe_ids = vuln.get("CweIDs") or []
    cwe_or_category = cwe_ids[0] if cwe_ids else rule_id

    message = vuln.get("Title") or vuln.get("Description") or rule_id

    return Finding(
        tool=TOOL_NAME,
        rule_id=rule_id,
        severity=severity_from_trivy(vuln.get("Severity", "")),
        file_path=target,
        # Trivy's dependency-level vulnerability entries carry no per-line
        # location (they describe a resolved package version, not a source
        # line) -- `1` is a documented placeholder, not a real location,
        # mirroring how `fingerprint.py`'s line-banding degrades gracefully
        # for tools with no native line signal.
        line_start=1,
        line_end=1,
        message=message,
        cwe_or_category=cwe_or_category,
        remediation=remediation,
        raw_ref=f"{TOOL_NAME}:{mode}#{index}",
    )


def _normalize_misconfiguration(
    misconf: dict[str, Any], target: str, mode: str, index: int
) -> Finding:
    rule_id = misconf.get("ID") or misconf["AVDID"]
    cause = misconf.get("CauseMetadata") or {}
    message = misconf.get("Message") or misconf.get("Title", "")

    return Finding(
        tool=TOOL_NAME,
        rule_id=rule_id,
        severity=severity_from_trivy(misconf.get("Severity", "")),
        file_path=target,
        line_start=cause.get("StartLine", 1),
        line_end=cause.get("EndLine", 1),
        message=message,
        cwe_or_category=rule_id,
        # Misconfigurations have no native mechanical fix path -- `structural`
        # guidance only, never JS/TS-lockfile-boundaried (this story's own
        # AC bullet 4).
        remediation=Remediation(
            kind="structural", patch=None, target_version=None, lockfile_managed=False
        ),
        raw_ref=f"{TOOL_NAME}:{mode}#{index}",
    )


def normalize_trivy(raw_output: str, mode: str) -> list[Finding]:
    """Parse one Trivy ``--format json`` payload (from any of the `fs`,
    `config`, or `image` subcommands -- the top-level ``Results`` shape is
    identical across all three) into `Finding` records (spec §8.1).

    ``mode`` (``"fs"`` | ``"config"`` | ``"image"``) is used only to prefix
    `raw_ref` so findings combined from multiple `run_trivy()` subprocess
    calls (each its own raw output artifact) never collide -- it plays no
    role in classification. Which branch a `Result` entry's findings take
    (`version_bump` vs. `structural`) is decided by that entry's own
    ``Class`` field (see module docstring Deviation 3), not by ``mode``.

    Pure function over the raw JSON text. Trivy writes a top-level
    ``"Results": null`` (not ``[]``) when nothing was found for that
    invocation -- both are treated identically as "no results", mirroring
    `gitleaks_runner.py`'s identical `null`-vs-empty-list handling. Raises
    `json.JSONDecodeError` on invalid JSON and `KeyError`/`TypeError` on a
    structurally-unexpected payload (missing ``Results`` key entirely, or a
    result/entry missing a required field) -- `run_trivy()` below catches
    both and maps them to the non-fatal `ScanStatus.FAILED` path (PRD
    requirement 18); this function itself stays a strict,
    total-over-its-documented-input-shape parser rather than silently
    swallowing structural errors.

    Only ``Status == "FAIL"`` (or absent -- Trivy omits `Status` entirely on
    some always-failing check types) misconfiguration rows become findings;
    ``"PASS"`` rows (present when the scan was run without suppressing
    passing checks) are not findings and are excluded.
    """
    data = json.loads(raw_output)
    results = data["Results"] or []

    findings: list[Finding] = []
    index = 0
    for result in results:
        target = result["Target"]
        result_class = result.get("Class")

        if result_class == "config":
            for misconf in result.get("Misconfigurations") or []:
                if misconf.get("Status") == "PASS":
                    continue
                findings.append(_normalize_misconfiguration(misconf, target, mode, index))
                index += 1
        else:
            for vuln in result.get("Vulnerabilities") or []:
                findings.append(_normalize_vulnerability(vuln, target, mode, index))
                index += 1

    return findings


def _run_mode(cmd: list[str], mode: str, timeout: int) -> tuple[list[Finding], str | None]:
    """Run one Trivy subcommand and normalize its output. Returns
    ``(findings, error_reason)`` -- ``error_reason`` is `None` on success,
    populated (and ``findings`` is ``[]``) on a crash-to-start
    (`OSError`), a timeout (`subprocess.TimeoutExpired`), or
    unparseable/structurally-unexpected stdout -- mirrors
    `run_semgrep()`/`run_gitleaks()`'s per-call non-fatal-failure handling,
    generalized here to per-mode within a single tool.
    """
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return [], f"trivy {mode} timed out after {timeout}s"
    except OSError as exc:
        return [], f"trivy {mode} failed to start: {exc}"

    try:
        findings = normalize_trivy(proc.stdout, mode=mode)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        return [], f"unparseable trivy {mode} output: {exc}"

    return findings, None


def run_trivy(workspace: Path, timeout: int) -> ScanResult:
    """Run Trivy's `fs`, `config`, and conditional `image` modes against
    `workspace` and normalize their combined output into one `ScanResult`
    (spec §8.5, PRD requirements 16/17/53/54; see module docstring
    Deviation 1 for why this is three subprocess calls, not one).

    `fs` and `config` always run. `image` mode runs only when `workspace`
    contains a `Dockerfile` with a parseable `FROM` line (module docstring
    Deviation 2) -- when absent, `image` mode is skipped entirely (no
    subprocess call is made at all), which is non-fatal (PRD requirement
    17): the aggregate result still reflects `PASSED`/`FAILED` from
    `fs`/`config` alone.

    Each attempted mode's subprocess call is bounded independently by
    `timeout` (PRD requirement 19 -- callers pass `config.SCANNER_TIMEOUT`,
    no shared budget is read from here or split across the up-to-three
    calls). If *any attempted* mode crashes, times out, or produces
    unparseable output, the aggregate `ScanResult.status` is
    `ScanStatus.FAILED` (PRD requirement 18) with `findings=[]` and a
    `reason` naming every failed mode -- a mode that failed does not get to
    contribute partial findings alongside a mode that succeeded, keeping
    this tool's own success/failure semantics as unambiguous as the other
    four scanners' single-call contract. Never raises: every mocked/real
    subprocess failure path is caught inside `_run_mode()`.
    """
    fs_findings, fs_error = _run_mode(_build_fs_command(workspace), "fs", timeout)
    config_findings, config_error = _run_mode(_build_config_command(workspace), "config", timeout)

    errors = [e for e in (fs_error, config_error) if e is not None]
    all_findings = list(fs_findings) + list(config_findings)

    base_image = _first_base_image(workspace)
    if base_image is not None:
        image_findings, image_error = _run_mode(_build_image_command(base_image), "image", timeout)
        all_findings.extend(image_findings)
        if image_error is not None:
            errors.append(image_error)

    if errors:
        return ScanResult(
            tool=TOOL_NAME,
            status=ScanStatus.FAILED,
            findings=[],
            reason="; ".join(errors),
        )

    return ScanResult(tool=TOOL_NAME, status=ScanStatus.PASSED, findings=all_findings, reason=None)
