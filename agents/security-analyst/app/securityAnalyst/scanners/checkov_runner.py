"""
Checkov scanner integration -- IaC-file skip detection + normalization
(spec §8.1/§8.5, PRD requirement 17/23/58 row 4, D30, story S-131).

Fourth concrete scanner -- follows `semgrep_runner.py`'s (S-128),
`gitleaks_runner.py`'s (S-129), and `trivy_runner.py`'s (S-130)
`run_<tool>(workspace, timeout) -> ScanResult` shape verbatim, importing
`ScanResult`/`ScanStatus` from `scanners.types` rather than redefining them.

This is the story that first exercises the `medium` unknown-severity floor
(`severity.py`'s `_UNKNOWN_SEVERITY_FLOOR`, D30) against real tool output:
Checkov's OSS checks (the overwhelming majority of its ruleset) carry no
native `severity` field at all -- only Bridgecrew-assigned or custom-policy
checks do. `severity_from_checkov()` (S-126, already merged) is imported
verbatim, never reimplemented here.

`remediation.kind = "structural"` is set unconditionally for every Checkov
finding, never `None` and never `"version_bump"` -- PRD requirement 23's
table lists Checkov as always routing to `Bucket.MANUAL` by way of
`classifier.py`'s (S-134) structural-remediation default branch (spec §8.4).
This is a hard rule, not a per-check judgment call.

**Deviation 1 -- Checkov's real `--output json` top-level shape is either a
single object or an array of objects, not always one or the other.** Neither
spec §8.1a's inline pseudocode nor the sequence diagram (spec §4.3, "`checkov
--output json`") specifies this, but Checkov's actual CLI behavior is: when
exactly one check-type/"framework" (Terraform, Dockerfile, Kubernetes,
CloudFormation, ...) matches content in the scanned directory, `--output
json` prints a single JSON object (`{"check_type": ..., "results": {...},
"summary": {...}}`); when more than one framework matches (the mixed-repo
case this story's own edge-case matrix calls out -- "mixed repo with both
Terraform and a Dockerfile"), it prints a JSON **array** of that same
per-framework object shape instead. `normalize_checkov()` below accepts
both: a bare object is treated as a one-element list of reports. This is the
same class of pre-authorized "apply proactively" correctness fix as
`trivy_runner.py`'s `Class`-field branching (Deviation 3 there) -- built
from Checkov's actual documented output behavior, not from a literal (and,
here, underspecified) reading of the spec's inline snippets.

**Deviation 2 -- `file_path` normalization.** Checkov's `failed_checks[].file_path`
is scan-root-relative but is written with a leading `/` (e.g. `"/main.tf"`
when scanning with `-d <workspace>`) -- not an absolute filesystem path, just
a leading separator convention. This module strips exactly one leading `/`
so Checkov's findings are bare-repo-relative at the normalizer, per spec
§8.1's `file_path` docstring ("repo-relative, normalized separators").

S-141 correction to the original wording here: it is NOT true that every
other normalizer already emits bare-relative paths -- the real Semgrep and
Gitleaks binaries echo the absolute workspace path they are invoked with
(only Trivy and CodeQL are scan-root-relative). Cross-tool consistency of
`file_path` (and therefore `fingerprint()`'s `file_path`-keyed hash and
`dedupe()`'s `(file_path, cwe_or_category)` grouping key, PRD requirement
22) is ultimately guaranteed by `run_scanners()`'s `_relativize_findings()`
in `scanners/__init__.py`, not by any per-tool normalizer. This strip must
nevertheless stay: `relativize_path()` treats a leading-`/` path as
absolute, and an absolute path *outside* the workspace is deliberately
left untouched -- so an unstripped `/main.tf` would survive to the dedup
key as-is and never match Trivy's `main.tf`.

**IaC-file detection (`has_iac_files()`) -- requirement 17's skip condition,
the canonical example spec §8.5 uses for this behavior.** Checkov itself has
no "nothing to scan" signal distinct from "scanned and found zero issues"
(an empty-but-still-a-JSON-report `--output json` payload looks identical to
a directory with no IaC content at all once at least one framework's parser
runs against zero matching files -- Checkov does not refuse to run or emit a
special code for "no matching files"). This module therefore performs its
own pre-flight detection, mirroring `trivy_runner.py`'s `_first_base_image()`
pre-flight check for `image` mode: a best-effort, deliberately simple
file-system scan for Terraform (`*.tf`/`*.tf.json`), Dockerfile
(`Dockerfile`/`Dockerfile.*`), CloudFormation, and Kubernetes manifest
content. CloudFormation/Kubernetes have no distinguishing file extension (both
are plain YAML/JSON), so those two are detected by a bounded content sniff
(`AWSTemplateFormatVersion` for CloudFormation; the co-occurrence of
`apiVersion:` and `kind:` for Kubernetes) rather than a full YAML/JSON parse
-- this keeps the detector dependency-free (no PyYAML addition to
`pyproject.toml` for a single pre-flight check) and matches the same
"good enough, not a full parser" tradeoff `trivy_runner.py`'s
`_parse_version_tuple()` makes for its own narrower purpose. Vendored/VCS
directories (`.git`, `node_modules`, `.venv`, `.terraform`, cache dirs) are
skipped so a dependency's own bundled Terraform fixtures (if any), a
`terraform init`-populated local module cache, or the agent's own
virtualenv content never produce a false positive (S-131 fidelity audit).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from normalize import Finding, Remediation
from scanners.types import ScanResult, ScanStatus
from severity import severity_from_checkov

TOOL_NAME = "checkov"

_TERRAFORM_SUFFIXES = (".tf", ".tf.json")
_CONTENT_SNIFF_SUFFIXES = (".yaml", ".yml", ".json")
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
_CLOUDFORMATION_MARKER = "AWSTemplateFormatVersion"
_CONTENT_SNIFF_MAX_BYTES = 65_536  # bounded read -- pre-flight check, not a full parse


def _is_dockerfile(name: str) -> bool:
    return name == "Dockerfile" or name.startswith("Dockerfile.")


def _is_terraform(name: str) -> bool:
    return name.endswith(_TERRAFORM_SUFFIXES)


def _sniff_text(path: Path) -> str:
    try:
        with path.open(encoding="utf-8", errors="ignore") as handle:
            return handle.read(_CONTENT_SNIFF_MAX_BYTES)
    except OSError:
        return ""


def _looks_like_cloudformation(text: str) -> bool:
    return _CLOUDFORMATION_MARKER in text


def _looks_like_kubernetes_manifest(text: str) -> bool:
    return "apiVersion:" in text and "kind:" in text


def has_iac_files(workspace: Path) -> bool:
    """Best-effort detection of any Terraform/CloudFormation/Kubernetes/
    Dockerfile content under `workspace` (see module docstring). Returns
    `True` on the first match found; `False` when nothing IaC-shaped is
    present at all -- the requirement 17 / AC-23 skip condition.
    """
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in files:
            if _is_terraform(name) or _is_dockerfile(name):
                return True
            if name.endswith(_CONTENT_SNIFF_SUFFIXES):
                text = _sniff_text(Path(root) / name)
                if _looks_like_cloudformation(text) or _looks_like_kubernetes_manifest(text):
                    return True
    return False


def _build_command(workspace: Path) -> list[str]:
    return ["checkov", "-d", str(workspace), "--output", "json", "--compact"]


def _normalize_file_path(raw_path: str) -> str:
    """Strip Checkov's leading `/` scan-root-relative separator (module
    docstring Deviation 2). Required even though `run_scanners()` now
    relativizes all tools' paths: a leading `/` reads as an absolute path
    outside the workspace there and would be left untouched.
    """
    return raw_path.lstrip("/")


def _normalize_check(check: dict[str, Any], index: int) -> Finding:
    rule_id = check["check_id"]
    file_path = _normalize_file_path(check["file_path"])
    line_range = check.get("file_line_range") or [1, 1]
    message = check.get("check_name") or rule_id

    return Finding(
        tool=TOOL_NAME,
        rule_id=rule_id,
        severity=severity_from_checkov(check.get("severity")),
        file_path=file_path,
        line_start=line_range[0],
        line_end=line_range[1],
        message=message,
        # Checkov carries no CWE/OWASP metadata -- falls back to rule_id,
        # mirroring Semgrep's/Gitleaks'/Trivy's identical last-resort
        # fallback so the cross-tool dedup key (`fingerprint()`'s
        # `rule_id or cwe_or_category`) is never empty.
        cwe_or_category=rule_id,
        # Unconditional structural remediation -- see module docstring.
        # Checkov is never mechanical in v1 (PRD requirement 23 table).
        remediation=Remediation(
            kind="structural", patch=None, target_version=None, lockfile_managed=False
        ),
        raw_ref=f"{TOOL_NAME}#{index}",
    )


def normalize_checkov(raw_output: str) -> list[Finding]:
    """Parse one Checkov `--output json` payload into `Finding` records
    (spec §8.1, PRD requirement 58 row 4 / D30).

    Pure function over the raw JSON text. Accepts both of Checkov's real
    top-level shapes (module docstring Deviation 1): a single per-framework
    report object, or a JSON array of them (the multi-framework case, e.g. a
    repo with both Terraform and a Dockerfile). Raises `json.JSONDecodeError`
    on invalid JSON, `TypeError` when the top-level value is neither an
    object nor an array (or the array contains non-object entries), and
    `KeyError` on a report/check missing a required field -- `run_checkov()`
    below catches all three and maps them to the non-fatal `ScanStatus.FAILED`
    path (PRD requirement 18); this function itself stays a strict,
    total-over-its-documented-input-shape parser rather than silently
    swallowing structural errors.

    A report's `results.failed_checks` being `null` (as opposed to `[]`) is
    treated identically as "no failures" -- mirrors `trivy_runner.py`'s and
    `gitleaks_runner.py`'s identical `null`-vs-empty-list handling for their
    own tools' "nothing found" shapes. Only `failed_checks` entries become
    findings; `passed_checks`/`skipped_checks` are not findings.
    """
    data = json.loads(raw_output)
    if isinstance(data, dict):
        reports: list[Any] = [data]
    elif isinstance(data, list):
        reports = data
    else:
        raise TypeError(
            f"expected a JSON object or array of per-framework reports, got {type(data).__name__}"
        )

    findings: list[Finding] = []
    index = 0
    for report in reports:
        results = report["results"]
        failed_checks = results.get("failed_checks") or []
        for check in failed_checks:
            findings.append(_normalize_check(check, index))
            index += 1

    return findings


def run_checkov(workspace: Path, timeout: int) -> ScanResult:
    """Run Checkov against `workspace` and normalize its output (spec §8.5,
    PRD requirement 17/18/19/23, AC-23).

    Pre-flight: when `has_iac_files(workspace)` is `False`, no subprocess
    call is made at all -- returns `ScanStatus.SKIPPED` with a named
    `reason` (requirement 17 / AC-23, the spec's own canonical example of
    this non-fatal outcome). A skip is never conflated with `FAILED`
    (crash/timeout/unparseable output) or `PASSED` (ran, found nothing) --
    `SKIPPED` is its own distinct, named `ScanStatus` value (`scanners.types`,
    already introduced by S-130's `image`-mode skip handling and reused here
    verbatim).

    When IaC is present, enforces `timeout` independently of any other
    scanner (PRD requirement 19 -- callers pass `config.SCANNER_TIMEOUT`, no
    shared timeout budget is read from here). A crash-to-start (`OSError` --
    e.g. the `checkov` binary missing from the image), a timeout
    (`subprocess.TimeoutExpired`), or unparseable/structurally-unexpected
    stdout are all non-fatal to the overall run (PRD requirement 18): each
    maps to `ScanStatus.FAILED` with `findings=[]` and a `reason` describing
    what happened, never an exception raised out of this function.
    """
    if not has_iac_files(workspace):
        return ScanResult(
            tool=TOOL_NAME,
            status=ScanStatus.SKIPPED,
            findings=[],
            reason=(
                "no IaC files present (no Terraform/CloudFormation/Kubernetes/Dockerfile "
                "content detected)"
            ),
        )

    cmd = _build_command(workspace)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return ScanResult(
            tool=TOOL_NAME,
            status=ScanStatus.FAILED,
            findings=[],
            reason=f"checkov timed out after {timeout}s",
        )
    except OSError as exc:
        return ScanResult(
            tool=TOOL_NAME,
            status=ScanStatus.FAILED,
            findings=[],
            reason=f"checkov failed to start: {exc}",
        )

    try:
        findings = normalize_checkov(proc.stdout)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        return ScanResult(
            tool=TOOL_NAME,
            status=ScanStatus.FAILED,
            findings=[],
            reason=f"unparseable checkov output: {exc}",
        )

    return ScanResult(tool=TOOL_NAME, status=ScanStatus.PASSED, findings=findings, reason=None)
