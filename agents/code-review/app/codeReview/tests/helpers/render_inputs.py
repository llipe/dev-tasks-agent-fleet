"""
Factories for the comment renderer's inputs (S-212).

``render.render_review`` reads a ``validate.Validation``, the
``budget.ContextData`` of the accepted call, the run's ``DiffContext`` and
``VerifierContext``. These helpers build them directly, so the renderer tests
can shape every field (lengths, hostile text, huge line numbers) without the
prompt builder or the model.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from budget import BlockNote, ContextData
from context.diff import DiffContext, FileDiff, NameOnlyFile
from context.verifier import (
    REPORT_NONE,
    REPORT_NOT_PARSEABLE,
    REPORT_PARSED,
    Candidate,
    VerifierContext,
    VerifierReport,
)
from validate import (
    NOT_CHECKED_REASON,
    STATUS_CONFIRMED,
    STATUS_DROPPED_FOR_BUDGET,
    STATUS_NOT_CHECKED,
    STATUS_NOT_REPRODUCED,
    VERDICT_BLOCKING,
    VERDICT_CLEAR,
    CandidateStatus,
    Finding,
    Validation,
    ValidationCounts,
)

RUN_ID = "0b7c4e9a-1d2f-4a3b-8c5d-6e7f8091a2b3"
HEAD = "9f2c4e1a7b3d5f60812a4c6e8b0d2f4a6c8e0b1d"
MERGE_BASE = "7e1d3c5b9a8f6e4d2c0b1a3f5e7d9c8b6a4f2e0d"
MODEL = "us.openai.sol-v1:0"
PANEL = "https://dt-agent-fleet-panel.fly.dev"
REPORT = "workstream/fidelity-report-S-170.md"
ISSUE_REPORT = "workstream/fidelity-report-issue-315.md"
SPEC = "workstream/specification-prd-webhook-triggers.md"
RUN_URL = f"{PANEL}/runs/{RUN_ID}"


def finding(
    fid: str,
    *,
    category: str = "correctness",
    file: str = "src/app.py",
    line_start: int = 1,
    line_end: int | None = None,
    title: str = "A title",
    failure_scenario: str = "it fails",
    consequence: str = "it breaks",
    rank: int | None = None,
    downgraded: str | None = None,
) -> Finding:
    severity = "blocking" if fid.startswith("B") else "suggestion"
    number = int(fid[1:])
    return Finding(
        id=fid,
        severity=severity,
        category=category,
        file=file,
        line_start=line_start,
        line_end=line_start if line_end is None else line_end,
        title=title,
        failure_scenario=failure_scenario,
        consequence=consequence,
        rank=number if rank is None else rank,
        downgraded=downgraded,
        index=number,
    )


def candidate(k: int, text: str, *, report: str = REPORT, row: int | None = None) -> Candidate:
    return Candidate(
        id=f"V{k}",
        report_path=report,
        row_index=k if row is None else row,
        line=10 + k,
        text=text,
        truncated=False,
    )


def status(c: Candidate, state: str, reason: str | None = None) -> CandidateStatus:
    if state in (STATUS_NOT_CHECKED, STATUS_DROPPED_FOR_BUDGET):
        return CandidateStatus(c, state, NOT_CHECKED_REASON, True)
    assert reason is not None
    return CandidateStatus(c, state, reason, state == STATUS_CONFIRMED)


def counts() -> ValidationCounts:
    return ValidationCounts(
        findings_in=0,
        kept=0,
        downgraded={},
        dropped={},
        suggestions_capped=0,
        findings_by_severity={},
        findings_by_category={},
        verifier_candidates=0,
        verifier_confirmed=0,
        verifier_by_status={},
        verifier_checks_ignored=0,
        verifier_checks_duplicate=0,
        downgraded_span=0,
    )


def validation(
    blocking: Sequence[Finding] = (),
    suggestions: Sequence[Finding] = (),
    candidates: Sequence[CandidateStatus] = (),
    *,
    verdict: str | None = None,
) -> Validation:
    if verdict is None:
        counted = any(c.counted for c in candidates)
        verdict = VERDICT_BLOCKING if blocking or counted else VERDICT_CLEAR
    return Validation(
        verdict=verdict,
        blocking=tuple(blocking),
        suggestions=tuple(suggestions),
        dropped=(),
        candidates=tuple(candidates),
        counts=counts(),
    )


def context_data(
    *,
    notes: Sequence[BlockNote] = (),
    full_files_included: Sequence[str] = (),
    full_files_dropped: Sequence[str] = (),
    issue_numbers: Sequence[int] = (),
    spec_paths: Sequence[str] = (),
    no_issues: bool | None = None,
    issues_unavailable: bool = False,
    no_spec: bool | None = None,
    verifier_state: str = REPORT_NONE,
    verifier_unavailable: bool = False,
    shown: Sequence[Candidate] = (),
    dropped: Sequence[Candidate] = (),
) -> ContextData:
    return ContextData(
        max_context_tokens=150_000,
        instruction_tokens=6_000,
        diff_tokens=1_000,
        total_tokens=7_000,
        remaining_tokens=143_000,
        unallocated_tokens=143_000,
        placed=(),
        notes=tuple(notes),
        shown_candidates=tuple(shown),
        dropped_candidates=tuple(dropped),
        full_files_included=tuple(full_files_included),
        full_files_dropped=tuple(full_files_dropped),
        issue_numbers=tuple(issue_numbers),
        spec_paths=tuple(spec_paths),
        no_issues=(not issue_numbers and not issues_unavailable)
        if no_issues is None
        else no_issues,
        issues_unavailable=issues_unavailable,
        no_spec=(not spec_paths) if no_spec is None else no_spec,
        verifier_state=verifier_state,
        verifier_unavailable=verifier_unavailable,
    )


def file_diff(filename: str, *, base_withheld: str | None = None) -> FileDiff:
    return FileDiff(
        filename=filename,
        status="modified",
        previous_filename=None,
        diff="",
        head_content="x\n",
        changed_ranges=((1, 1),),
        base_withheld=base_withheld,
    )


def diff_ctx(files: Sequence[FileDiff] = (), name_only: Sequence[NameOnlyFile] = ()) -> DiffContext:
    return DiffContext(HEAD, MERGE_BASE, 10, tuple(files), tuple(name_only))


def report(
    path: str,
    state: str,
    *,
    candidates: Sequence[Candidate] = (),
    other_drift: int = 0,
) -> VerifierReport:
    return VerifierReport(
        path=path,
        issue=315,
        state=state,
        section="## Drift\n" if state == REPORT_PARSED else "",
        section_truncated=False,
        section_tokens=3 if state == REPORT_PARSED else 0,
        candidates=tuple(candidates),
        other_drift=other_drift,
    )


def verifier_ctx(*reports: VerifierReport, unavailable: bool = False) -> VerifierContext:
    cands = tuple(c for r in reports for c in r.candidates)
    return VerifierContext(tuple(reports), cands, unavailable)


# ---------------------------------------------------------------------------
# The snapshot fixtures
# ---------------------------------------------------------------------------


def blocking_fixture() -> dict:
    """The "blocking" snapshot: every section, a little hostile text, all states."""
    v1 = candidate(1, "| DR-1 | Critical | Unintended | retries are not idempotent |")
    v2 = candidate(2, "| DR-4 | Critical | Unintended | no audit row on refund |", row=4)
    v3 = candidate(3, "| DR-6 | Critical | Unintended | webhook secret logged |", row=6)
    blocking = (
        finding(
            "B1",
            file="src/app.py",
            line_start=120,
            line_end=134,
            title="Retry double-charges on timeout",
            failure_scenario=(
                "the gateway times out after the charge is accepted, and `retry()` sends it again"
            ),
            consequence="the customer is charged twice; ping @payments-team",
        ),
        finding(
            "B2",
            category="edge_case",
            file="src/limits.py",
            line_start=42,
            title="Zero limit <b>divides</b> by zero",
            failure_scenario="limit = 0",
            consequence="ZeroDivisionError crashes the worker",
        ),
    )
    suggestions = (
        finding(
            "S1",
            category="maintainability",
            file="src/app.py",
            line_start=10,
            title="Extract the retry policy",
            consequence="Two call sites will drift.",
        ),
        finding(
            "S2",
            file="src/old.py",
            line_start=5,
            line_end=9,
            title="Dead branch",
            consequence="Readers waste time on it.",
            downgraded="outside_diff",
        ),
    )
    statuses = (
        status(v1, STATUS_CONFIRMED, "Still visible in src/app.py at this head."),
        status(v2, STATUS_NOT_REPRODUCED, "Fixed by the new idempotency key."),
        status(v3, STATUS_DROPPED_FOR_BUDGET),
    )
    return {
        "validation": validation(blocking, suggestions, statuses),
        "context": context_data(
            notes=(BlockNote("spec", SPEC, "trimmed", "cap"),),
            full_files_included=("src/limits.py",),
            full_files_dropped=("src/app.py", "src/old.py"),
            issue_numbers=(315,),
            spec_paths=(SPEC,),
            verifier_state=REPORT_PARSED,
            shown=(v1, v2),
            dropped=(v3,),
        ),
        "diff": diff_ctx(
            files=(
                file_diff("src/app.py"),
                file_diff("src/limits.py"),
                file_diff("src/moved.py", base_withheld="excluded"),
            ),
            name_only=(
                NameOnlyFile("pnpm-lock.yaml", "modified", "lockfile"),
                NameOnlyFile("assets/logo.png", "added", "binary"),
            ),
        ),
        "verifier": verifier_ctx(
            report(REPORT, REPORT_PARSED, candidates=(v1, v2, v3), other_drift=3),
            report(ISSUE_REPORT, REPORT_NONE),
        ),
    }


def clear_fixture() -> dict:
    """The "clear" snapshot: no findings, no report, no issue, no spec."""
    return {
        "validation": validation(),
        "context": context_data(),
        "diff": diff_ctx(files=(file_diff("src/app.py"),)),
        "verifier": verifier_ctx(),
    }


def with_context(fixture: dict, **changes) -> dict:
    out = dict(fixture)
    out["context"] = replace(fixture["context"], **changes)
    return out


__all__ = [
    "HEAD",
    "ISSUE_REPORT",
    "MODEL",
    "PANEL",
    "REPORT",
    "REPORT_NONE",
    "REPORT_NOT_PARSEABLE",
    "REPORT_PARSED",
    "RUN_ID",
    "RUN_URL",
    "SPEC",
    "blocking_fixture",
    "candidate",
    "clear_fixture",
    "context_data",
    "counts",
    "diff_ctx",
    "file_diff",
    "finding",
    "report",
    "status",
    "validation",
    "verifier_ctx",
    "with_context",
]
