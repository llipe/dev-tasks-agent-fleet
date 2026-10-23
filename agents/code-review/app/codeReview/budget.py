"""
Budget fit (S-209; spec §8.4; D-27, D-37).

Let ``B = max_context_tokens``. Every token here is ``context/tokens.estimate``
(``ceil(chars / 3.5)``), re-exported below; this module defines no estimator.

1. **Mandatory** (``I + D``): the instructions ``I`` (the system prompt in its
   fallback form, which carries the ``submit_review`` schema and is the larger
   of the two forms the adapter can send, plus the wrapper's preamble and a
   fixed reserve for the closing notes) and the diff block ``D`` (the expanded
   diff and the files listed by name only, with its label and markers). Over
   ``B``, ``prompt.build_prompt`` returns ``OverBudget`` and builds nothing
   else (PRD FR-6).
2. **Priority fill** of ``R = B - I - D`` (``fill``), in ``FILL_ORDER`` a–g.
   A piece's content allowance is ``min(cap, R_left - overhead)``, where
   ``overhead`` is what the wrapper renders around the content (label, marker
   lines, separators) and is charged to ``R_left`` as well. A truncatable
   piece over its allowance is cut at a line boundary with ``[truncated]``
   (``context.tokens.truncate``); an allowance of 0 or less, or a cut that
   leaves only the marker, omits it. Caps:

   - a. PR title and body: ``PR_TOKEN_CAP`` (4,000);
   - b. verifier candidates: whole (already cut to 300 by S-208), in order,
     while they fit; the first that does not fit and every later one are
     dropped (``Fill.dropped_candidates``, counted as not shown, D-37);
   - c. issues: ``min(8,000 x n, 30% of R)`` split equally among the ``n``
     issues, with no redistribution of a short issue's unused share;
   - d. drift sections: ``min(4,000 x n, 10% of R)`` split equally among the
     ``n`` parsed reports (the spec's "4,000 per report, 10% of R");
   - e. specs: 30% of ``B`` split equally (``context.spec.spec_cap``);
   - f. conventions: 10% of ``B`` (``context.repo_conventions.conventions_cap``);
   - g. full files: whole, smallest rendered cost first (ties in files-list
     order), while they fit; the rest are dropped. This is the set PRD FR-5's
     "drop largest-first" gives.

3. **Invariant** (``assert_within_budget``): the caller measures the final
   prompt, ``estimate(fallback system) + estimate(user message)``, and this
   raises ``BudgetInvariantError`` (``INTERNAL_ERROR``) when it is over ``B``.
   It is an explicit ``raise``, so it holds under ``python -O``. Pieces are
   charged one by one and ``ceil`` is subadditive, so the fill never
   under-counts the concatenated prompt.

Caps bound the *content*; the wrapper text around it is charged to
``R_left`` on top, so every rendered character is paid for. ``fill`` is pure:
it sees lengths and strings, never GitHub, and renders nothing itself; the
overhead of each piece comes from ``prompt.py``, which owns the rendering.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from context.conventions import DRIFT_SECTION_TOKEN_CAP, ISSUE_TOKEN_CAP
from context.diff import DiffContext
from context.issues import IssuesContext
from context.repo_conventions import ConventionsContext, conventions_cap
from context.spec import SpecContext, spec_cap
from context.tokens import TRUNCATION_MARKER, estimate, estimate_len, truncate
from context.verifier import Candidate, VerifierContext

__all__ = [
    "BLOCK_CANDIDATE",
    "BLOCK_CONVENTIONS",
    "BLOCK_DIFF",
    "BLOCK_FILE",
    "BLOCK_ISSUE",
    "BLOCK_PR",
    "BLOCK_SPEC",
    "BLOCK_VERIFIER",
    "FILL_ORDER",
    "NAME_ONLY_TOKEN_CAP",
    "NOTES_RESERVE_TOKENS",
    "PR_TOKEN_CAP",
    "REASON_BUDGET",
    "REASON_CAP",
    "STATE_OMITTED",
    "STATE_TRIMMED",
    "STATE_TRUNCATED",
    "BlockNote",
    "BudgetInvariantError",
    "ContextData",
    "ContextInputs",
    "Fill",
    "FillGroups",
    "Piece",
    "PieceUse",
    "Placed",
    "assert_within_budget",
    "estimate",
    "estimate_len",
    "fill",
    "prompt_tokens",
]

# Block kinds, as they appear in the nonce markers (spec §8.5).
BLOCK_PR = "pr"
BLOCK_ISSUE = "issue"
BLOCK_SPEC = "spec"
BLOCK_VERIFIER = "verifier"
BLOCK_CANDIDATE = "verifier-candidate"
BLOCK_CONVENTIONS = "conventions"
BLOCK_DIFF = "diff"
BLOCK_FILE = "file"

# Spec §8.4 a–g.
FILL_ORDER = (
    BLOCK_PR,
    BLOCK_CANDIDATE,
    BLOCK_ISSUE,
    BLOCK_VERIFIER,
    BLOCK_SPEC,
    BLOCK_CONVENTIONS,
    BLOCK_FILE,
)

PR_TOKEN_CAP = 4_000
ISSUES_SHARE_NUMERATOR, ISSUES_SHARE_DENOMINATOR = 3, 10  # 30% of R
DRIFT_SHARE_NUMERATOR, DRIFT_SHARE_DENOMINATOR = 1, 10  # 10% of R
# The files listed by name only go inside the mandatory diff block; a PR with
# thousands of generated files cannot push the diff over budget by its names.
NAME_ONLY_TOKEN_CAP = 1_000
# Room kept inside ``I`` for the wrapper's closing notes (states and counts).
NOTES_RESERVE_TOKENS = 250

STATE_TRUNCATED = "truncated"
STATE_TRIMMED = "trimmed"  # the spec, cut to its sections upstream (S-207)
STATE_OMITTED = "omitted"
REASON_CAP = "cap"  # cut to a cap (here or by the S-207/S-208 reader)
REASON_BUDGET = "budget"  # cut or omitted because ``R_left`` ran out

_MARKER_LINE = TRUNCATION_MARKER + "\n"


class BudgetInvariantError(Exception):
    """The final prompt is over ``max_context_tokens``: a fill bug (spec §8.4 step 3).

    Not a GitHub or model failure; the run ends ``failed``/``INTERNAL_ERROR``,
    never with a silent overrun. The message holds only the two numbers.
    """

    code = "INTERNAL_ERROR"

    def __init__(self, tokens: int, max_context_tokens: int) -> None:
        self.tokens = tokens
        self.max_context_tokens = max_context_tokens
        super().__init__(
            f"budget invariant violated: prompt estimate {tokens} tokens"
            f" > max_context_tokens {max_context_tokens}"
        )


# ---------------------------------------------------------------------------
# Inputs and results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContextInputs:
    """Everything the prompt is built from: the outputs of S-206..S-208.

    ``pr_title``/``pr_body`` are the author's claim (PRD FR-12); every text
    field here is untrusted. ``None`` for a reader that did not run.
    """

    pr_number: int
    head_sha: str
    pr_title: str
    pr_body: str
    diff: DiffContext
    issues: IssuesContext | None = None
    spec: SpecContext | None = None
    verifier: VerifierContext | None = None
    conventions: ConventionsContext | None = None


@dataclass(frozen=True)
class Piece:
    """One unit the fill places, truncates, or drops.

    ``content`` is the text inside the markers, ending with ``\\n``.
    ``overhead`` is the number of characters the renderer adds around it.
    ``upstream`` names cuts an earlier reader already made (``trimmed``,
    ``truncated``), reported with ``REASON_CAP``. ``index`` is the position
    in the source order (files-list order for files).
    """

    block: str
    ref: str | None
    content: str
    overhead: int
    truncatable: bool = True
    upstream: tuple[str, ...] = ()
    index: int = 0


@dataclass(frozen=True)
class Placed:
    piece: Piece
    content: str  # as rendered: whole, or cut with ``[truncated]``
    truncated: bool
    reason: str | None  # REASON_CAP | REASON_BUDGET when truncated here
    tokens: int  # charged: content plus overhead


@dataclass(frozen=True)
class FillGroups:
    pr: Piece | None = None
    candidates: Sequence[Piece] = ()
    issues: Sequence[Piece] = ()
    reports: Sequence[Piece] = ()
    specs: Sequence[Piece] = ()
    conventions: Piece | None = None
    files: Sequence[Piece] = ()


@dataclass(frozen=True)
class Fill:
    remaining: int  # R = B - I - D
    unallocated: int  # R_left after the fill
    placed: tuple[Placed, ...]  # in fill order
    omitted: tuple[Piece, ...]  # truncatable pieces with no room
    dropped_candidates: tuple[Piece, ...]
    dropped_files: tuple[Piece, ...]


# ---------------------------------------------------------------------------
# The fill
# ---------------------------------------------------------------------------


def _cost(overhead: int, content: int) -> int:
    """Tokens charged for a piece: its content plus the wrapper text around it."""
    return estimate_len(overhead + content)


def _meaningful(content: str, cut: bool) -> bool:
    """A cut that keeps only the marker (or whitespace) is no block at all."""
    if not content:
        return False
    if not cut:
        return True
    return bool(content[: -len(_MARKER_LINE)].strip())


@dataclass
class _Filler:
    left: int
    placed: list[Placed] = field(default_factory=list)
    omitted: list[Piece] = field(default_factory=list)

    def capped(self, piece: Piece, cap: int) -> None:
        """Place ``piece`` with a content allowance of ``min(cap, R_left - overhead)``."""
        room = self.left - _cost(piece.overhead, 0)
        allowance = min(cap, room)
        if allowance <= 0:
            self.omitted.append(piece)
            return
        content, cut = truncate(piece.content, allowance)
        if not _meaningful(content, cut):
            self.omitted.append(piece)
            return
        reason = (REASON_BUDGET if room < cap else REASON_CAP) if cut else None
        self._place(piece, content, cut, reason)

    def whole_prefix(self, pieces: Sequence[Piece]) -> tuple[Piece, ...]:
        """Place whole pieces in order while they fit; return the dropped rest."""
        for k, piece in enumerate(pieces):
            if _cost(piece.overhead, len(piece.content)) > self.left:
                return tuple(pieces[k:])
            self._place(piece, piece.content, False, None)
        return ()

    def shared(self, pieces: Sequence[Piece], total_cap: int) -> None:
        """Split ``total_cap`` equally; each piece then gets ``min(share, R_left)``."""
        if not pieces:
            return
        share = total_cap // len(pieces)
        for piece in pieces:
            self.capped(piece, share)

    def _place(self, piece: Piece, content: str, cut: bool, reason: str | None) -> None:
        tokens = _cost(piece.overhead, len(content))
        self.left -= tokens
        self.placed.append(Placed(piece, content, cut, reason, tokens))


def fill(groups: FillGroups, *, max_context_tokens: int, mandatory_tokens: int) -> Fill:
    """Fill ``R = max_context_tokens - mandatory_tokens`` in spec §8.4 order a–g."""
    remaining = max_context_tokens - mandatory_tokens
    if remaining < 0:
        raise ValueError("the mandatory part is over budget; return OverBudget instead")
    f = _Filler(remaining)
    if groups.pr is not None:
        f.capped(groups.pr, PR_TOKEN_CAP)  # a
    dropped_candidates = f.whole_prefix(groups.candidates)  # b
    n = len(groups.issues)  # c
    f.shared(
        groups.issues,
        min(ISSUE_TOKEN_CAP * n, remaining * ISSUES_SHARE_NUMERATOR // ISSUES_SHARE_DENOMINATOR),
    )
    n = len(groups.reports)  # d
    f.shared(
        groups.reports,
        min(
            DRIFT_SECTION_TOKEN_CAP * n,
            remaining * DRIFT_SHARE_NUMERATOR // DRIFT_SHARE_DENOMINATOR,
        ),
    )
    f.shared(groups.specs, spec_cap(max_context_tokens))  # e
    if groups.conventions is not None:
        f.capped(groups.conventions, conventions_cap(max_context_tokens))  # f
    files = sorted(
        groups.files, key=lambda p: (_cost(p.overhead, len(p.content)), p.index)
    )  # g: smallest first
    dropped_files = f.whole_prefix(files)
    return Fill(
        remaining=remaining,
        unallocated=f.left,
        placed=tuple(f.placed),
        omitted=tuple(f.omitted),
        dropped_candidates=dropped_candidates,
        dropped_files=dropped_files,
    )


# ---------------------------------------------------------------------------
# Context data (for S-211's verdict and S-212's context line)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BlockNote:
    """A block that was cut or left out, for the comment's context line (§8.4 step 4).

    ``block`` is a kind (``pr``, ``issue``, ``spec``, ``verifier``,
    ``conventions``); ``ref`` is ``#<n>`` for an issue, the path for a spec or
    report, ``None`` otherwise. ``state`` is ``truncated``, ``trimmed`` or
    ``omitted``; ``reason`` is ``cap`` or ``budget``.
    """

    block: str
    ref: str | None
    state: str
    reason: str


@dataclass(frozen=True)
class PieceUse:
    """A placed piece: what it cost, for run_events and tests."""

    block: str
    ref: str | None
    tokens: int  # charged, labels and markers included
    content_tokens: int  # the content alone
    truncated: bool


@dataclass(frozen=True)
class ContextData:
    """What went into the prompt and what did not.

    Candidates: ``shown_candidates`` reached the model; ``dropped_candidates``
    did not (budget) and S-211 counts them as not checked, so they block
    (spec §8.4 step 5, §8.7, D-37). Together they are every candidate, in order.
    Files: ``full_files_included`` and ``full_files_dropped`` are in
    smallest-first order; together they are every reviewed, non-removed file.
    Paths here are raw repository text: render them neutralized (S-212).
    """

    max_context_tokens: int
    instruction_tokens: int  # fallback system prompt + preamble + notes reserve
    diff_tokens: int  # the diff block, label and markers included
    total_tokens: int  # estimate(fallback system) + estimate(user message)
    remaining_tokens: int  # R
    unallocated_tokens: int  # R_left after the fill
    placed: tuple[PieceUse, ...]  # fill order
    notes: tuple[BlockNote, ...]
    shown_candidates: tuple[Candidate, ...]
    dropped_candidates: tuple[Candidate, ...]
    full_files_included: tuple[str, ...]
    full_files_dropped: tuple[str, ...]
    issue_numbers: tuple[int, ...]  # issues shown, in order
    spec_paths: tuple[str, ...]  # specs shown, in order
    no_issues: bool  # no linked issue was read
    issues_unavailable: bool  # an issue read was refused (403)
    no_spec: bool  # "no spec found"
    verifier_state: str  # ``VerifierContext.state``: none | not_parseable | parsed
    verifier_unavailable: bool  # a report read was refused (403)

    @property
    def mandatory_tokens(self) -> int:
        return self.instruction_tokens + self.diff_tokens

    @property
    def block_tokens(self) -> dict[str, int]:
        """Tokens charged per block kind, plus ``instructions`` and ``diff``."""
        out = {"instructions": self.instruction_tokens, BLOCK_DIFF: self.diff_tokens}
        for kind in FILL_ORDER:
            out[kind] = 0
        for use in self.placed:
            out[use.block] += use.tokens
        return out

    @property
    def truncated(self) -> tuple[BlockNote, ...]:
        return tuple(n for n in self.notes if n.state != STATE_OMITTED)

    @property
    def omitted(self) -> tuple[BlockNote, ...]:
        return tuple(n for n in self.notes if n.state == STATE_OMITTED)


# ---------------------------------------------------------------------------
# Invariant
# ---------------------------------------------------------------------------


class _Measured(Protocol):
    @property
    def fallback_system(self) -> str: ...

    @property
    def user(self) -> str: ...


def prompt_tokens(prompt: _Measured) -> int:
    """The estimate of the whole prompt the adapter may send (fallback system + user)."""
    return estimate(prompt.fallback_system) + estimate(prompt.user)


def assert_within_budget(tokens: int, max_context_tokens: int) -> None:
    """Raise ``BudgetInvariantError`` when ``tokens > max_context_tokens``."""
    if tokens > max_context_tokens:
        raise BudgetInvariantError(tokens, max_context_tokens)
