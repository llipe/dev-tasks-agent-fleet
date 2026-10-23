"""
Factories for the prompt builder's inputs (S-209).

``build_prompt`` takes the outputs of the S-206..S-208 context readers. These
helpers build them directly, without GitHub, so the budget and prompt tests
can shape each block's size and content.
"""

from __future__ import annotations

from collections.abc import Sequence

from budget import ContextInputs
from context.diff import DiffContext, FileDiff, NameOnlyFile
from context.issues import IssuesContext, LinkedIssue
from context.repo_conventions import ConventionsContext
from context.spec import ResolvedSpec, SpecContext
from context.verifier import REPORT_PARSED, Candidate, VerifierContext, VerifierReport

HEAD = "9f2c4e1a7b3d5f60812a4c6e8b0d2f4a6c8e0b1d"
MB = "7e1d3c5b9a8f6e4d2c0b1a3f5e7d9c8b6a4f2e0d"
NONCE = "0123456789abcdef"
OTHER_NONCE = "fedcba9876543210"


def file_diff(
    filename: str,
    head: str | None = "line\n",
    *,
    diff: str | None = None,
    status: str = "modified",
) -> FileDiff:
    if diff is None:
        diff = f"--- a/{filename}\n+++ b/{filename}\n@@ -1 +1 @@\n-old\n+new\n"
    return FileDiff(
        filename=filename,
        status=status,
        previous_filename=None,
        diff=diff,
        head_content=head,
        changed_ranges=((1, 1),) if head is not None else (),
    )


def diff_ctx(
    files: Sequence[FileDiff] = (),
    name_only: Sequence[NameOnlyFile] = (),
    *,
    changed_lines: int = 2,
) -> DiffContext:
    if not files:
        files = (file_diff("src/app.py"),)
    return DiffContext(HEAD, MB, changed_lines, tuple(files), tuple(name_only))


def issue(number: int, body: str = "Issue body.\n", title: str | None = None) -> LinkedIssue:
    return LinkedIssue(
        number=number,
        title=title if title is not None else f"[PRD-widgets] Story S-{number:03d}: title",
        labels=("prd:widgets",),
        body=body,
        stripped_body=body,
        checklist_stripped=False,
        truncated=False,
    )


def issues_ctx(*issues: LinkedIssue, unavailable: bool = False) -> IssuesContext:
    return IssuesContext(tuple(i.number for i in issues), tuple(issues), (), unavailable)


def spec(
    path: str = "workstream/specification-prd-widgets.md", text: str = "# Spec\n"
) -> ResolvedSpec:
    return ResolvedSpec(path, text, False, False, 0, 41)


def spec_ctx(*specs: ResolvedSpec) -> SpecContext:
    return SpecContext(tuple(specs), (), (), ())


def candidate(
    k: int, text: str = "| D1 | Critical | Unintended | row |", path: str | None = None
) -> Candidate:
    return Candidate(
        id=f"V{k}",
        report_path=path or "workstream/fidelity-report-S-001.md",
        row_index=k,
        line=10 + k,
        text=text,
        truncated=False,
    )


def report(
    path: str = "workstream/fidelity-report-S-001.md",
    section: str = "## Drift\n\n| ID | Impact | Intent |\n| --- | --- | --- |\n",
    candidates: Sequence[Candidate] = (),
) -> VerifierReport:
    return VerifierReport(path, 41, REPORT_PARSED, section, False, 0, tuple(candidates), 0)


def verifier_ctx(*reports: VerifierReport) -> VerifierContext:
    cands = tuple(c for r in reports for c in r.candidates)
    return VerifierContext(tuple(reports), cands)


def conventions_ctx(text: str = "AGENTS.md at head:\nUse ruff.\n") -> ConventionsContext:
    return ConventionsContext("AGENTS.md", (), 0, text, False, 0)


def inputs(
    *,
    diff: DiffContext | None = None,
    title: str = "Add widget sizes",
    body: str = "Closes #41\n",
    issues: IssuesContext | None = None,
    specs: SpecContext | None = None,
    verifier: VerifierContext | None = None,
    conventions: ConventionsContext | None = None,
) -> ContextInputs:
    return ContextInputs(
        pr_number=42,
        head_sha=HEAD,
        pr_title=title,
        pr_body=body,
        diff=diff if diff is not None else diff_ctx(),
        issues=issues,
        spec=specs,
        verifier=verifier,
        conventions=conventions,
    )


# ---------------------------------------------------------------------------
# Reading a rendered prompt back
# ---------------------------------------------------------------------------


def parse_blocks(user: str, nonce: str) -> tuple[list[tuple[str, str | None, str]], str]:
    """Split ``user`` on the real nonce: ``([(kind, tag, content)], outside)``.

    Independent of the builder: a block opens at a line
    ``<<<UNTRUSTED <kind> [<tag> ]<nonce>>>>`` and closes at the next line
    ``<<<END <nonce>>>``. ``outside`` is every line not inside a block, marker
    lines excluded. Raises ``AssertionError`` on an unclosed block or a stray
    end marker.
    """
    end = f"<<<END {nonce}>>>"
    suffix = f" {nonce}>>>"
    blocks: list[tuple[str, str | None, str]] = []
    outside: list[str] = []
    current: tuple[str, str | None] | None = None
    body: list[str] = []
    for line in user.split("\n"):
        if current is None:
            assert line != end, "end marker outside a block"
            if line.startswith("<<<UNTRUSTED ") and line.endswith(suffix):
                words = line[len("<<<UNTRUSTED ") : -len(suffix)].split(" ")
                assert 1 <= len(words) <= 2, line
                current = (words[0], words[1] if len(words) == 2 else None)
                body = []
            else:
                outside.append(line)
        elif line == end:
            blocks.append((current[0], current[1], "\n".join(body) + "\n"))
            current = None
        else:
            body.append(line)
    assert current is None, "unclosed block"
    return blocks, "\n".join(outside)
