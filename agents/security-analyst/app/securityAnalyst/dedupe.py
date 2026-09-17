"""
Cross-tool deduplication (spec §8.3, PRD requirement 22 / D19, story S-133).

``dedupe()`` merges findings that describe "the same underlying issue"
reported independently by two or more of the five scanners in a single scan
pass -- a distinct concept from ``fingerprint()`` (spec §8.2), which
identifies "the same finding" across re-scans of the same tool over time.
The two never share tolerance logic: ``fingerprint()``'s banded-line
tolerance (D18) exists to absorb unrelated line-shifting edits between
scans; this module's overlap check exists to recognize when two tools point
at the same code location within one scan, and is deliberately exact
(no banding) to keep the merge conservative (D19).

Merge criterion, per spec §8.3, is conservative by design: file path AND
category match (the grouping key) AND line-range overlap within that group.
Both conditions are required -- neither alone is sufficient -- so a real
second issue at the same line (different category) or the same category
elsewhere in the file (non-overlapping lines) is never hidden under an
over-eager merge (PRD AC8).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from normalize import Finding
from severity import Severity

# Severity rank for "highest-severity contributor wins" (task 9.2). Not
# exported by severity.py (which defines the enum but no total ordering), so
# defined locally, scoped to this module's one use: selecting a merged
# record's representative. Higher number = higher severity.
_SEVERITY_RANK: dict[Severity, int] = {
    Severity.LOW: 0,
    Severity.MEDIUM: 1,
    Severity.HIGH: 2,
    Severity.CRITICAL: 3,
}


@dataclass(frozen=True)
class MergedFinding:
    """A dedupe group's output record (spec §8.3).

    ``finding`` is the representative record: the highest-severity
    contributor in the group (task 9.2), with ties broken by first
    appearance in the input list (a deterministic, order-preserving choice
    absent from the spec's pseudocode, which is silent on ties).
    ``reported_by`` names every tool that contributed a finding to the
    group, deduplicated and in first-appearance order -- never a single
    tool, even for a group of one (a group of one still yields a
    ``reported_by`` of length 1, keeping the field's shape uniform for
    every downstream consumer).
    """

    finding: Finding
    reported_by: tuple[str, ...]


def dedupe(findings: list[Finding]) -> list[MergedFinding]:
    """Merge same-resource findings across tools within one scan pass.

    Groups by ``(file_path, cwe_or_category)`` -- never by tool, so
    same-category findings from different tools are candidates for merging
    -- then merges within each group by line-range overlap
    (``_merge_overlapping_by_line``). Group iteration order follows each
    group key's first appearance in ``findings`` (Python dict insertion
    order), and each group's internal merge order follows
    ``_merge_overlapping_by_line``'s own ordering, keeping the overall
    output deterministic for a given input order.
    """
    groups: dict[tuple[str, str], list[Finding]] = defaultdict(list)
    for finding in findings:
        groups[(finding.file_path, finding.cwe_or_category)].append(finding)

    merged: list[MergedFinding] = []
    for group in groups.values():
        merged.extend(_merge_overlapping_by_line(group))
    return merged


def _merge_overlapping_by_line(group: list[Finding]) -> list[MergedFinding]:
    """Merge a same-file/same-category group by line-range overlap.

    Two findings' ``[line_start, line_end]`` ranges are considered
    overlapping (and therefore merged) when they intersect, including at a
    single shared boundary line (``a.line_end == b.line_start`` counts as
    overlap, not a gap). This is a plain interval-merge: sort by
    ``line_start`` (stable, so ties preserve the caller's original relative
    order), then sweep left to right, extending the current cluster's
    running maximum ``line_end`` and starting a new cluster whenever the
    next finding's ``line_start`` falls strictly beyond it. This also
    correctly resolves chained (three-way-or-more) overlaps: if A overlaps
    B and B overlaps C, A and C end up in the same cluster even when A and
    C do not directly overlap, because the running maximum carries B's
    extent forward into the comparison against C.
    """
    if not group:
        return []

    ordered = sorted(group, key=lambda f: f.line_start)

    clusters: list[list[Finding]] = []
    current_cluster: list[Finding] = [ordered[0]]
    current_max_end = ordered[0].line_end

    for finding in ordered[1:]:
        if finding.line_start <= current_max_end:
            current_cluster.append(finding)
            current_max_end = max(current_max_end, finding.line_end)
        else:
            clusters.append(current_cluster)
            current_cluster = [finding]
            current_max_end = finding.line_end
    clusters.append(current_cluster)

    return [_to_merged_finding(cluster) for cluster in clusters]


def _to_merged_finding(cluster: list[Finding]) -> MergedFinding:
    """Build one cluster's ``MergedFinding`` (task 9.2).

    Representative is the highest-severity contributor; on a severity tie,
    the first contributor (in the cluster's own order, which follows
    ``_merge_overlapping_by_line``'s stable line-start sort) wins --
    deterministic and reproducible for identical input, not spec-mandated
    but required for the output to be stable across runs.
    """
    representative = cluster[0]
    best_rank = _SEVERITY_RANK[representative.severity]
    for finding in cluster[1:]:
        rank = _SEVERITY_RANK[finding.severity]
        if rank > best_rank:
            representative = finding
            best_rank = rank

    reported_by: list[str] = []
    for finding in cluster:
        if finding.tool not in reported_by:
            reported_by.append(finding.tool)

    return MergedFinding(finding=representative, reported_by=tuple(reported_by))
