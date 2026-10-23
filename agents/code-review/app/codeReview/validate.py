"""
Findings validation and verdict (S-211; spec §8.6, §8.7; D-08, D-15, D-33, D-37).

The wrapper enforces the blocking contract instead of trusting the model
(PRD FR-23): a blocking finding needs a location in the diff and a concrete
failure scenario, and every finding needs a consequence. The verdict is
computed here, never taken from the model.

``validate`` is pure: no I/O, no clock, no randomness. Every text operation is
linear in the input (the review is model output and untrusted).

**Inputs.**

- ``review``: the schema-valid ``submit_review`` input (spec §6.3). It is
  re-checked with ``findings_schema.validate_review``; a violation raises
  ``SchemaViolation``, which is a bug upstream (``INTERNAL_ERROR``).
- ``changed_ranges``: per reviewed file, its changed head line ranges
  (1-based inclusive; EC-07's deletion anchor included). Its keys are the
  reviewed files. ``validate_result`` builds it from the diff:
  ``DiffContext.changed_ranges`` (reviewed, fetched, non-removed files) plus
  each of ``DiffContext.removed_paths`` with no range. They never come from
  ``ContextData.full_files_included``, which is empty after an R4 retry or a
  repair although the files are still reviewed. Name-only files (lockfiles,
  generated, binary, excluded, content unavailable, including removed files
  moved there after the fetch) are not keys, so a finding on them is dropped.
- ``shown_candidates`` / ``dropped_candidates``: ``ContextData``'s candidates
  of the call that produced the accepted output.

**Rules, in spec §8.6 order** (the first rule that applies decides):

1. *Location.* ``file`` is matched to a reviewed path (``match_reviewed``);
   no match → dropped, ``reason: "not_reviewed"`` (DF-07). ``line_end <
   line_start`` is swapped. A ``blocking`` finding is *located in the diff*
   when its span intersects a changed range widened by ±3 lines **and** spans
   at most ``MAX_BLOCKING_SPAN`` (200) lines, ``line_end - line_start + 1``
   (D-50: a span of a whole file around one changed line points at no changed
   code). Not located → ``suggestion``, ``downgraded: "outside_diff"``; the
   reason covers both cases, so the artifact enum is unchanged. A reviewed
   file with no changed range (a pure rename, or a removed file: no head
   lines to anchor it) is outside the diff. A finding on a removed reviewed
   file is kept (planner decision on TC-211-05: "you deleted foo() and bar.py
   still calls it" is valuable).
2. *Scenario.* A finding still ``blocking`` with a blank ``failure_scenario``
   → ``suggestion``, ``downgraded: "no_scenario"``. A finding failing both
   checks is ``outside_diff`` (rule 1 applies first).
3. *Consequence.* A blank ``consequence`` → dropped, ``reason:
   "no_consequence"``, for both severities. A not-reviewed finding is
   ``not_reviewed`` (rule 1 first).
4. *Cap.* Suggestions (downgraded ones included) sorted by ``(rank, model
   order)``; beyond ``max_suggestions`` dropped, ``reason: "cap"``.
   ``max_suggestions = 0`` drops every suggestion. Blocking findings are never
   capped.
5. *IDs.* ``B1…Bn`` and ``S1…Sm``, each group in ``(rank, model order)``.

**Blank** (one definition, ``is_blank``; D-51): the text contains no Unicode
letter or number, that is no character whose ``unicodedata.category``
starts with ``L`` or ``N``, other than the Hangul fillers U+115F, U+1160,
U+3164 and U+FFA0 (category ``Lo``, rendered as nothing). Whitespace, controls, format characters
(zero-width ones, bidi controls), fillers, punctuation, symbols and
combining marks alone are all blank, so ``"."``, ``"-"`` and ``"…"`` carry no
scenario. There is no word deny-list: ``"N/A"`` and ``"none"`` contain
letters and are not blank. The empty string is blank.

**Paths** (``normalize_file``, ``match_reviewed``): the raw ``file`` is tried
first, then its normalized form: every leading and trailing backtick is
stripped, then leading ``./`` and ``/`` repeatedly. Each form is matched
exactly against the reviewed paths and against their ``escape_path`` forms
(control characters appear escaped in the diff headers). Nothing else
changes: no whitespace strip, no case folding, no ``\\`` to ``/``, and ``..``
or ``.`` segments are never resolved, so ``a/../b.py`` matches only a
reviewed path literally named ``a/../b.py``. A literal path match wins over
another file's escaped form; on a collision between two escaped forms the
first file in diff order wins. A kept finding's ``file`` is the canonical
reviewed path (raw repository text: S-212 neutralizes it).

**Lines and ranks** are Python ints of any size (the schema has no maximum).
They are only compared or subtracted (±3 on the ranges, the span length),
never converted or clamped, so ``10**300`` costs nothing and is kept exactly.
A span from 1 to ``10**300`` intersects every range but is longer than
``MAX_BLOCKING_SPAN``, so it is not a location (D-50). The location check uses a
bisect over the merged ranges, so it is ``O(log R)`` per finding.

**Verdict** (spec §8.7, D-33, D-37; ``candidate_statuses``):

- each ``dropped_candidates`` entry is ``dropped_for_budget`` and counts,
  even when the model returned a check for its ID;
- each ``shown_candidates`` entry is ``confirmed`` (counts),
  ``not_reproduced`` (does not count), or ``not_checked`` when the model
  omitted it (counts, reason "not checked by the model");
- checks for IDs not in ``shown_candidates`` are ignored; IDs match exactly
  (``V01`` is not ``V1``);
- duplicate checks for one ID (DF-12): any ``confirmed`` wins, with the first
  ``confirmed`` entry's reason; otherwise the first entry's reason;
- ``verdict = blocking`` when at least one blocking finding or one counted
  candidate remains, else ``clear``.

The model's reason is untrusted text: it is kept raw (S-212 neutralizes it)
and cut to ``REASON_MAX_CHARS``.

**Counts** (``ValidationCounts``, PRD FR-31, spec §5.3) hold numbers and
fixed enum keys only, never finding text. ``downgraded`` counts every
downgrade applied, including findings later dropped for no consequence or
the cap; ``dropped`` counts each drop by its one reason; so
``findings_in == kept + sum(dropped)``. ``suggestions_capped`` is the number
of suggestions dropped by the cap (0: the cap was not hit).
``verifier_confirmed`` counts the candidates that count toward ``blocking``
(spec §8.7 treats an omitted candidate as confirmed); ``verifier_by_status``
breaks them down.
"""

from __future__ import annotations

import bisect
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from context.diff import escape_path
from context.verifier import Candidate
from findings_schema import CATEGORIES, SEVERITIES, validate_review

__all__ = [
    "DOWNGRADE_NO_SCENARIO",
    "DOWNGRADE_OUTSIDE_DIFF",
    "DOWNGRADE_REASONS",
    "DROP_CAP",
    "DROP_NOT_REVIEWED",
    "DROP_NO_CONSEQUENCE",
    "DROP_REASONS",
    "LOCATION_WINDOW",
    "MAX_BLOCKING_SPAN",
    "NOT_CHECKED_REASON",
    "REASON_MAX_CHARS",
    "STATUS_CONFIRMED",
    "STATUS_DROPPED_FOR_BUDGET",
    "STATUS_NOT_CHECKED",
    "STATUS_NOT_REPRODUCED",
    "STATUSES",
    "VERDICT_BLOCKING",
    "VERDICT_CLEAR",
    "CandidateStatus",
    "DroppedFinding",
    "Finding",
    "Validation",
    "ValidationCounts",
    "candidate_statuses",
    "in_changed_range",
    "is_blank",
    "match_reviewed",
    "normalize_file",
    "validate",
    "validate_result",
]

LOCATION_WINDOW = 3  # spec §8.6 step 2: changed range widened by ±3 lines
MAX_BLOCKING_SPAN = 200  # D-50: longest span, in lines, a blocking finding may have

BLOCKING, SUGGESTION = SEVERITIES

DOWNGRADE_OUTSIDE_DIFF = "outside_diff"
DOWNGRADE_NO_SCENARIO = "no_scenario"
DOWNGRADE_REASONS = (DOWNGRADE_OUTSIDE_DIFF, DOWNGRADE_NO_SCENARIO)

DROP_NOT_REVIEWED = "not_reviewed"  # DF-07: the spec names no reason
DROP_NO_CONSEQUENCE = "no_consequence"
DROP_CAP = "cap"
DROP_REASONS = (DROP_NOT_REVIEWED, DROP_NO_CONSEQUENCE, DROP_CAP)

STATUS_CONFIRMED = "confirmed"
STATUS_NOT_REPRODUCED = "not_reproduced"
STATUS_NOT_CHECKED = "not_checked"
STATUS_DROPPED_FOR_BUDGET = "dropped_for_budget"
STATUSES = (STATUS_CONFIRMED, STATUS_NOT_REPRODUCED, STATUS_NOT_CHECKED, STATUS_DROPPED_FOR_BUDGET)
_COUNTED = frozenset({STATUS_CONFIRMED, STATUS_NOT_CHECKED, STATUS_DROPPED_FOR_BUDGET})

NOT_CHECKED_REASON = "not checked by the model"  # spec §8.7
REASON_MAX_CHARS = 300  # the schema's ``reason`` maxLength

VERDICT_BLOCKING = "blocking"
VERDICT_CLEAR = "clear"

# Hangul fillers: category Lo, but they render as nothing and are no letter.
_BLANK_FILLERS = frozenset("\u115f\u1160\u3164\uffa0")


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """A kept finding after validation. Text fields are raw model text."""

    id: str  # ``B<n>`` or ``S<n>``
    severity: str  # after any downgrade
    category: str
    file: str  # the canonical reviewed path (raw repository text)
    line_start: int  # ``line_start <= line_end`` (swapped if needed)
    line_end: int
    title: str
    failure_scenario: str
    consequence: str
    rank: int
    downgraded: str | None  # ``outside_diff`` | ``no_scenario`` | None
    index: int  # position in the model's ``findings`` list

    def as_artifact(self) -> dict[str, Any]:
        """The spec §5.2 artifact entry: the §6.3 fields plus ``id`` and ``downgraded``."""
        return {
            "id": self.id,
            "severity": self.severity,
            "category": self.category,
            "file": self.file,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "title": self.title,
            "failure_scenario": self.failure_scenario,
            "consequence": self.consequence,
            "rank": self.rank,
            "downgraded": self.downgraded if self.downgraded is not None else False,
        }


@dataclass(frozen=True)
class DroppedFinding:
    """A finding validation removed. ``file`` and ``title`` are raw model text."""

    index: int  # position in the model's ``findings`` list
    reason: str  # one of ``DROP_REASONS``
    severity: str  # at the time of the drop (after any downgrade)
    category: str
    file: str
    title: str
    rank: int
    downgraded: str | None

    def as_artifact(self) -> dict[str, Any]:
        """The spec §5.2 ``dropped`` entry."""
        return {"reason": self.reason, "title": self.title}


@dataclass(frozen=True)
class CandidateStatus:
    """What the verdict made of one drift candidate (for S-212's Verifier section).

    ``reason`` is the model's reason (raw, untrusted, cut to
    ``REASON_MAX_CHARS``) for ``confirmed`` and ``not_reproduced``, and the
    wrapper's ``NOT_CHECKED_REASON`` for ``not_checked`` and
    ``dropped_for_budget``.
    """

    candidate: Candidate
    status: str  # one of ``STATUSES``
    reason: str
    counted: bool

    @property
    def id(self) -> str:
        return self.candidate.id

    @property
    def reason_from_model(self) -> bool:
        return self.status in (STATUS_CONFIRMED, STATUS_NOT_REPRODUCED)


@dataclass(frozen=True)
class ValidationCounts:
    """Counts for ``runs.metrics`` (FR-31). Numbers and enum keys only."""

    findings_in: int
    kept: int
    downgraded: dict[str, int]  # every ``DOWNGRADE_REASONS`` key
    dropped: dict[str, int]  # every ``DROP_REASONS`` key
    suggestions_capped: int
    findings_by_severity: dict[str, int]  # kept findings; every severity key
    findings_by_category: dict[str, int]  # kept findings; every category key
    verifier_candidates: int
    verifier_confirmed: int  # counted toward blocking
    verifier_by_status: dict[str, int]  # every ``STATUSES`` key
    verifier_checks_ignored: int  # checks for IDs not shown to the model
    verifier_checks_duplicate: int  # extra checks for a shown ID

    def as_metrics(self) -> dict[str, Any]:
        """The spec §5.3 keys this story owns, plus the candidate breakdown."""
        return {
            "findings_by_severity": dict(self.findings_by_severity),
            "findings_by_category": dict(self.findings_by_category),
            "downgraded": dict(self.downgraded),
            "dropped": dict(self.dropped),
            "suggestions_capped": self.suggestions_capped,
            "verifier_candidates": self.verifier_candidates,
            "verifier_confirmed": self.verifier_confirmed,
            "verifier_by_status": dict(self.verifier_by_status),
            "verifier_checks_ignored": self.verifier_checks_ignored,
            "verifier_checks_duplicate": self.verifier_checks_duplicate,
        }


@dataclass(frozen=True)
class Validation:
    """The validated review: findings, drops, candidate statuses, verdict, counts."""

    verdict: str  # ``blocking`` | ``clear``
    blocking: tuple[Finding, ...]  # B1…, (rank, model order)
    suggestions: tuple[Finding, ...]  # S1…, (rank, model order), capped
    dropped: tuple[DroppedFinding, ...]  # model order
    candidates: tuple[CandidateStatus, ...]  # shown order, then dropped order
    counts: ValidationCounts

    @property
    def findings(self) -> tuple[Finding, ...]:
        """Blocking findings first, then suggestions."""
        return self.blocking + self.suggestions

    @property
    def counted_candidates(self) -> tuple[CandidateStatus, ...]:
        return tuple(c for c in self.candidates if c.counted)

    def metrics(self) -> dict[str, Any]:
        return self.counts.as_metrics()


# ---------------------------------------------------------------------------
# Text rules
# ---------------------------------------------------------------------------


def is_blank(text: str) -> bool:
    """True when ``text`` has no letter or number (D-51, module docstring).

    One pass that returns at the first letter or number.
    """
    category = unicodedata.category
    return not any(category(c)[0] in "LN" and c not in _BLANK_FILLERS for c in text)


def normalize_file(raw: str) -> str:
    """Strip surrounding backticks, then leading ``./`` and ``/``, repeatedly.

    Index-based, so hostile runs of prefixes stay linear.
    """
    text = raw.strip("`")
    start, end = 0, len(text)
    while start < end:
        if text.startswith("./", start):
            start += 2
        elif text[start] == "/":
            start += 1
        else:
            break
    return text[start:end]


def _lookup(paths: Iterable[str]) -> dict[str, str]:
    """Literal reviewed paths first, then their ``escape_path`` forms."""
    ordered = list(paths)
    table = {p: p for p in ordered}
    for p in ordered:
        table.setdefault(escape_path(p), p)
    return table


def _match(raw: str, table: Mapping[str, str]) -> str | None:
    found = table.get(raw)
    if found is None:
        found = table.get(normalize_file(raw))
    return found


def match_reviewed(raw: str, reviewed: Iterable[str]) -> str | None:
    """The reviewed path ``raw`` names, or ``None`` (see the module docstring)."""
    return _match(raw, _lookup(reviewed))


class _Ranges:
    """Merged, sorted ranges with a bisect over their ends."""

    def __init__(self, ranges: Iterable[tuple[int, int]]) -> None:
        merged: list[tuple[int, int]] = []
        for start, end in sorted(ranges):
            if merged and start <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        self._starts = [s for s, _ in merged]
        self._ends = [e for _, e in merged]

    def hits(self, line_start: int, line_end: int) -> bool:
        lo, hi = min(line_start, line_end), max(line_start, line_end)
        # The first range whose widened end reaches ``lo``.
        k = bisect.bisect_left(self._ends, lo - LOCATION_WINDOW)
        return k < len(self._ends) and self._starts[k] - LOCATION_WINDOW <= hi


def in_changed_range(line_start: int, line_end: int, ranges: Iterable[tuple[int, int]]) -> bool:
    """True when the (swapped if needed) span meets a range widened by ±3.

    Intersection only: ``validate`` also applies ``MAX_BLOCKING_SPAN`` (D-50).
    """
    return _Ranges(ranges).hits(line_start, line_end)


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _CheckTally:
    statuses: tuple[CandidateStatus, ...]
    ignored: int
    duplicate: int


def _tally(
    checks: Iterable[Mapping[str, Any]],
    shown: Sequence[Candidate],
    dropped: Sequence[Candidate],
) -> _CheckTally:
    shown_ids = {c.id for c in shown}
    first: dict[str, str] = {}  # id -> first entry's reason
    confirmed: dict[str, str] = {}  # id -> first confirmed entry's reason
    ignored = duplicate = 0
    for entry in checks:
        cid = entry["candidate_id"]
        if cid not in shown_ids:
            ignored += 1
            continue
        reason = entry["reason"][:REASON_MAX_CHARS]
        if cid in first:
            duplicate += 1
        else:
            first[cid] = reason
        if entry["status"] == STATUS_CONFIRMED and cid not in confirmed:
            confirmed[cid] = reason
    out: list[CandidateStatus] = []
    for c in shown:
        if c.id in confirmed:
            out.append(CandidateStatus(c, STATUS_CONFIRMED, confirmed[c.id], True))
        elif c.id in first:
            out.append(CandidateStatus(c, STATUS_NOT_REPRODUCED, first[c.id], False))
        else:
            out.append(CandidateStatus(c, STATUS_NOT_CHECKED, NOT_CHECKED_REASON, True))
    for c in dropped:
        out.append(CandidateStatus(c, STATUS_DROPPED_FOR_BUDGET, NOT_CHECKED_REASON, True))
    return _CheckTally(tuple(out), ignored, duplicate)


def candidate_statuses(
    checks: Iterable[Mapping[str, Any]],
    *,
    shown: Sequence[Candidate],
    dropped: Sequence[Candidate],
) -> tuple[CandidateStatus, ...]:
    """Per-candidate status, shown candidates first, then dropped ones (§8.7)."""
    return _tally(checks, shown, dropped).statuses


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class _Candidates(Protocol):
    @property
    def shown_candidates(self) -> tuple[Candidate, ...]: ...

    @property
    def dropped_candidates(self) -> tuple[Candidate, ...]: ...


class _Result(Protocol):
    """What ``validate_result`` reads from ``bedrock_adapter.ReviewResult``."""

    @property
    def findings(self) -> Mapping[str, Any]: ...

    @property
    def context(self) -> _Candidates: ...


class _Diff(Protocol):
    """What ``validate_result`` reads from ``context.diff.DiffContext``."""

    @property
    def changed_ranges(self) -> Mapping[str, tuple[tuple[int, int], ...]]: ...

    @property
    def removed_paths(self) -> tuple[str, ...]: ...


@dataclass
class _Kept:
    severity: str
    file: str
    line_start: int
    line_end: int
    downgraded: str | None
    index: int
    raw: Mapping[str, Any]


def _finding(k: _Kept, fid: str) -> Finding:
    r = k.raw
    return Finding(
        id=fid,
        severity=k.severity,
        category=r["category"],
        file=k.file,
        line_start=k.line_start,
        line_end=k.line_end,
        title=r["title"],
        failure_scenario=r["failure_scenario"],
        consequence=r["consequence"],
        rank=r["rank"],
        downgraded=k.downgraded,
        index=k.index,
    )


def _dropped(
    index: int, reason: str, raw: Mapping[str, Any], severity: str, downgraded: str | None
) -> DroppedFinding:
    return DroppedFinding(
        index=index,
        reason=reason,
        severity=severity,
        category=raw["category"],
        file=raw["file"],
        title=raw["title"],
        rank=raw["rank"],
        downgraded=downgraded,
    )


def validate(
    review: Mapping[str, Any],
    *,
    changed_ranges: Mapping[str, Iterable[tuple[int, int]]],
    shown_candidates: Sequence[Candidate],
    dropped_candidates: Sequence[Candidate],
    max_suggestions: int,
) -> Validation:
    """Apply spec §8.6 and §8.7 to a schema-valid review (see the module docstring)."""
    if type(max_suggestions) is not int or max_suggestions < 0:
        raise ValueError("max_suggestions must be a non-negative int")
    checked = validate_review(review)
    table = _lookup(changed_ranges)
    prepared: dict[str, _Ranges] = {}

    downgraded = dict.fromkeys(DOWNGRADE_REASONS, 0)
    dropped: list[DroppedFinding] = []
    kept: list[_Kept] = []
    findings = checked["findings"]
    for index, raw in enumerate(findings):
        name = _match(raw["file"], table)
        if name is None:
            dropped.append(_dropped(index, DROP_NOT_REVIEWED, raw, raw["severity"], None))
            continue
        start, end = raw["line_start"], raw["line_end"]
        if end < start:
            start, end = end, start
        severity, reason = raw["severity"], None
        if severity == BLOCKING:
            ranges = prepared.get(name)
            if ranges is None:
                ranges = prepared[name] = _Ranges(changed_ranges[name])
            if end - start + 1 > MAX_BLOCKING_SPAN or not ranges.hits(start, end):
                reason = DOWNGRADE_OUTSIDE_DIFF
            elif is_blank(raw["failure_scenario"]):
                reason = DOWNGRADE_NO_SCENARIO
            if reason is not None:
                severity = SUGGESTION
                downgraded[reason] += 1
        if is_blank(raw["consequence"]):
            dropped.append(_dropped(index, DROP_NO_CONSEQUENCE, raw, severity, reason))
            continue
        kept.append(_Kept(severity, name, start, end, reason, index, raw))

    def order(k: _Kept) -> tuple[int, int]:
        return (k.raw["rank"], k.index)

    blocking_kept = sorted((k for k in kept if k.severity == BLOCKING), key=order)
    suggestion_kept = sorted((k for k in kept if k.severity == SUGGESTION), key=order)
    capped = suggestion_kept[max_suggestions:]
    suggestion_kept = suggestion_kept[:max_suggestions]
    for k in capped:
        dropped.append(_dropped(k.index, DROP_CAP, k.raw, SUGGESTION, k.downgraded))
    dropped.sort(key=lambda d: d.index)

    blocking = tuple(_finding(k, f"B{n}") for n, k in enumerate(blocking_kept, 1))
    suggestions = tuple(_finding(k, f"S{n}") for n, k in enumerate(suggestion_kept, 1))

    tally = _tally(checked["verifier_checks"], shown_candidates, dropped_candidates)
    counted = sum(1 for c in tally.statuses if c.counted)
    verdict = VERDICT_BLOCKING if blocking or counted else VERDICT_CLEAR

    by_reason = dict.fromkeys(DROP_REASONS, 0)
    for d in dropped:
        by_reason[d.reason] += 1
    by_severity = dict.fromkeys(SEVERITIES, 0)
    by_category = dict.fromkeys(CATEGORIES, 0)
    for f in blocking + suggestions:
        by_severity[f.severity] += 1
        by_category[f.category] += 1
    by_status = dict.fromkeys(STATUSES, 0)
    for c in tally.statuses:
        by_status[c.status] += 1

    counts = ValidationCounts(
        findings_in=len(findings),
        kept=len(blocking) + len(suggestions),
        downgraded=downgraded,
        dropped=by_reason,
        suggestions_capped=len(capped),
        findings_by_severity=by_severity,
        findings_by_category=by_category,
        verifier_candidates=len(tally.statuses),
        verifier_confirmed=counted,
        verifier_by_status=by_status,
        verifier_checks_ignored=tally.ignored,
        verifier_checks_duplicate=tally.duplicate,
    )
    return Validation(verdict, blocking, suggestions, tuple(dropped), tally.statuses, counts)


def validate_result(result: _Result, diff: _Diff, *, max_suggestions: int) -> Validation:
    """``validate`` on a ``ReviewResult`` and the run's ``DiffContext``.

    Reviewed files are ``diff.changed_ranges``' keys plus ``diff.removed_paths``
    (with no range, so a blocking finding there is ``outside_diff``); the
    candidates come from ``result.context`` (the call that produced the
    accepted output).
    """
    reviewed: dict[str, Iterable[tuple[int, int]]] = dict(diff.changed_ranges)
    for path in diff.removed_paths:
        reviewed.setdefault(path, ())
    return validate(
        result.findings,
        changed_ranges=reviewed,
        shown_candidates=result.context.shown_candidates,
        dropped_candidates=result.context.dropped_candidates,
        max_suggestions=max_suggestions,
    )
