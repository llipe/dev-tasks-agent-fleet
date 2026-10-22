"""
File classification, size check, and the expanded diff (S-206).

Spec §8.2 and §8.3 step 1; decisions D-11 (no partial review) and D-26
(the ±50-line diff is built locally from blobs).

Flow (``diff_context``):

1. ``classify`` sorts the PR's files into *reviewed* and *listed by name only*
   (lockfiles, generated paths, binaries, excluded workstream files) from the
   path and the files-response metadata alone. Both names of a rename are
   classified: the new name decides reviewed vs name-only, and a previous name
   matching the excluded-workstream, lockfile or generated rules withholds the
   base (``base_withheld_reason``).
2. ``check_size`` sums additions + deletions over reviewed files. Over
   ``max_diff_lines``, or a file listing cut at the 3,000-file cap, returns
   ``OverBudget`` and nothing else is fetched: no merge base, no content.
3. ``expanded_diff`` reads the merge base through ``compare`` and fetches the
   merge-base and head blobs with a pool of ``MAX_WORKERS`` threads, then
   emits ``difflib.unified_diff(n=50)`` per file, the head contents, and the
   changed head line ranges. A file whose base is withheld is never fetched at
   its previous name: it is diffed as if added (``/dev/null`` base, every head
   line ``+``), so excluded content cannot leak as ``-`` lines (FR-10, AC-8)
   and a rename out of an excluded path cannot hide new code from review.

Late reclassification: a fetched blob with a NUL byte in its first 8 KB is
binary, and a blob that cannot be fetched is "content unavailable". Both move
the file to the name-only list. Their lines were already counted by the size
check, which runs before any content exists (DF-22).

Errors: GitHub failures propagate unchanged (``GitHubApiError``,
``GitHubPermissionDenied``). A 404 on ``compare`` propagates as
``GitHubNotFound`` for the pipeline (S-213) to map; a 404 on a blob is not an
error here (content unavailable). A file path the client guard refuses
(``ForbiddenCall``, for example a name containing ``\\``) is content
unavailable too: the guard still blocks the request, the run goes on without
that file's content.

Thread safety: ``requests`` does not document ``Session`` as thread-safe, so
each worker thread lazily builds its own ``GitHubClient`` (and with it its own
transport) from ``client_factory``; clients are never shared across threads.
Results are collected in submission order, so the output follows the
files-list order whatever order the fetches complete in.
"""

from __future__ import annotations

import difflib
import re
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

from github_client import (
    ForbiddenCall,
    GitHubApiError,
    GitHubClient,
    PullFile,
    PullFiles,
    PullRequest,
)

__all__ = [
    "CONTEXT_LINES",
    "LOCKFILE_NAMES",
    "MAX_WORKERS",
    "NUL_SCAN_BYTES",
    "Classification",
    "DiffContext",
    "FileDiff",
    "NameOnlyFile",
    "OverBudget",
    "base_withheld_reason",
    "changed_lines",
    "changed_ranges",
    "check_size",
    "classify",
    "diff_context",
    "expanded_diff",
    "path_reason",
    "split_lines",
    "unified_diff",
]

CONTEXT_LINES = 50  # D-26
MAX_WORKERS = 8  # spec §11
NUL_SCAN_BYTES = 8192  # "a NUL byte in the first 8 KB" (spec §8.2)

LOCKFILE_NAMES = frozenset(
    {
        "pnpm-lock.yaml",
        "package-lock.json",
        "yarn.lock",
        "poetry.lock",
        "uv.lock",
        "Pipfile.lock",
        "Cargo.lock",
        "go.sum",
        "Gemfile.lock",
        "composer.lock",
    }
)
GENERATED_DIRS = frozenset({"dist", "build"})
GENERATED_SUFFIXES = (".min.js", ".min.css", ".map", ".snap")
EXCLUDED_WORKSTREAM = re.compile(r"workstream/(?:tasks|planner-state|decisions|research)-[^/]*\.md")

_SHA_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")

UNAVAILABLE_UNSAFE_PATH = "path cannot be fetched safely"
UNAVAILABLE_NOT_FOUND = "not found at the reviewed commit"


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NameOnlyFile:
    """A changed file the prompt names but never includes.

    ``reason``: ``lockfile``, ``generated``, ``binary``, ``excluded``, or
    ``content_unavailable`` (with ``detail`` saying why).
    """

    filename: str
    status: str
    reason: str
    detail: str | None = None


@dataclass(frozen=True)
class Classification:
    reviewed: tuple[PullFile, ...]
    name_only: tuple[NameOnlyFile, ...]


@dataclass(frozen=True)
class OverBudget:
    """The PR exceeds ``max_diff_lines`` (PRD FR-6): budget comment, no review.

    ``lines`` and ``files`` count reviewed files. With ``truncated`` the file
    listing hit the 3,000-file cap, so both are lower bounds.
    """

    lines: int
    files: int
    max_diff_lines: int
    truncated: bool = False


@dataclass(frozen=True)
class FileDiff:
    """One reviewed file: its ±50-line diff, head content, and changed ranges."""

    filename: str
    status: str
    previous_filename: str | None
    diff: str
    head_content: str | None  # None for removed files
    changed_ranges: tuple[tuple[int, int], ...]
    # The name-only rule (``excluded``, ``lockfile``, ``generated``) the
    # previous name matched, when the base was withheld and the file was
    # diffed as added; ``None`` otherwise. For the comment's context line.
    base_withheld: str | None = None


@dataclass(frozen=True)
class DiffContext:
    head_sha: str
    merge_base_sha: str | None  # None when no file is reviewed (nothing to diff)
    changed_lines: int
    files: tuple[FileDiff, ...]
    # Classification name-only files first, then files moved there after the
    # fetch (binary by NUL, content unavailable), each group in files-list order.
    name_only: tuple[NameOnlyFile, ...]

    @property
    def diff_text(self) -> str:
        """The expanded diff of every reviewed file, in files-list order."""
        return "".join(f.diff for f in self.files)

    @property
    def head_contents(self) -> dict[str, str]:
        """Head content per reviewed, non-removed file (spec §8.3 step 6)."""
        return {f.filename: f.head_content for f in self.files if f.head_content is not None}

    @property
    def changed_ranges(self) -> dict[str, tuple[tuple[int, int], ...]]:
        """Changed head line ranges per reviewed, non-removed file (S-211)."""
        return {f.filename: f.changed_ranges for f in self.files if f.head_content is not None}


# ---------------------------------------------------------------------------
# Classification and size check (spec §8.2)
# ---------------------------------------------------------------------------


def path_reason(path: str) -> str | None:
    """The name-only reason a path alone implies, or ``None`` (reviewed)."""
    if EXCLUDED_WORKSTREAM.fullmatch(path):
        return "excluded"
    *dirs, base = path.split("/")
    if base in LOCKFILE_NAMES:
        return "lockfile"
    if any(d in GENERATED_DIRS for d in dirs) or base.endswith(GENERATED_SUFFIXES):
        return "generated"
    return None


def base_withheld_reason(f: PullFile) -> str | None:
    """The rule a rename's previous name matches, when its base must not be read.

    ``None`` when there is no previous name or it is an ordinary path. The
    size check still counts the file's additions and deletions as GitHub
    reports them.
    """
    if f.previous_filename is None:
        return None
    return path_reason(f.previous_filename)


def _looks_binary(f: PullFile) -> bool:
    """No ``patch`` and no line counts: GitHub's shape for a binary file.

    GitHub also omits ``patch`` for very large text diffs and for pure
    renames. Those carry line counts or the ``renamed`` status, stay reviewed,
    and are budgeted; the NUL check on their content still catches a binary.
    """
    return f.patch is None and f.additions == 0 and f.deletions == 0 and f.status != "renamed"


def classify(files: Iterable[PullFile]) -> Classification:
    """Split ``files`` into reviewed and name-only, keeping files-list order.

    Only the head name (``filename``) decides this. A reviewed file whose
    previous name is name-only stays reviewed with its base withheld (see
    ``base_withheld_reason``), so a rename cannot hide new code from review.
    """
    reviewed: list[PullFile] = []
    name_only: list[NameOnlyFile] = []
    for f in files:
        reason = path_reason(f.filename)
        if reason is None and _looks_binary(f):
            reason = "binary"
        if reason is None:
            reviewed.append(f)
        else:
            name_only.append(NameOnlyFile(f.filename, f.status, reason))
    return Classification(tuple(reviewed), tuple(name_only))


def changed_lines(classification: Classification) -> int:
    """Σ (additions + deletions) over reviewed files."""
    return sum(f.additions + f.deletions for f in classification.reviewed)


def check_size(
    classification: Classification, max_diff_lines: int, *, truncated: bool = False
) -> OverBudget | None:
    """``OverBudget`` when over the line budget or the listing was cut (D-11)."""
    lines = changed_lines(classification)
    if truncated or lines > max_diff_lines:
        return OverBudget(lines, len(classification.reviewed), max_diff_lines, truncated)
    return None


# ---------------------------------------------------------------------------
# Text diffs (D-26)
# ---------------------------------------------------------------------------


def split_lines(text: str) -> list[str]:
    """Lines with their ``\\n`` kept, split on ``\\n`` only.

    ``str.splitlines`` also splits on ``\\r``, form feed, U+2028 and others,
    which would shift line numbers away from the ones GitHub shows.
    """
    parts = text.split("\n")
    lines = [p + "\n" for p in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def _header_path(prefix: str, path: str) -> str:
    """``a/<path>``, with control characters escaped so a name cannot add lines."""
    escaped = "".join(
        c if c >= " " and c != "\x7f" else c.encode("unicode_escape").decode("ascii") for c in path
    )
    return prefix + escaped


def unified_diff(base_path: str, head_path: str, base: str, head: str, status: str) -> str:
    """``difflib.unified_diff(n=50)`` of two texts, as one string.

    ``added`` diffs from ``/dev/null`` and ``removed`` to ``/dev/null``. A line
    without a final newline is followed by git's ``\\ No newline at end of
    file`` marker, so it cannot merge into the next diff line. Equal texts give
    ``""``.
    """
    from_file = "/dev/null" if status == "added" else _header_path("a/", base_path)
    to_file = "/dev/null" if status == "removed" else _header_path("b/", head_path)
    out: list[str] = []
    for line in difflib.unified_diff(
        split_lines(base), split_lines(head), from_file, to_file, n=CONTEXT_LINES
    ):
        if line.endswith("\n"):
            out.append(line)
        else:
            out.append(line + "\n\\ No newline at end of file\n")
    return "".join(out)


def _merge(ranges: Iterable[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return tuple(merged)


def changed_ranges(base: str, head: str) -> tuple[tuple[int, int], ...]:
    """1-based inclusive head line ranges touched by the change.

    Uses the matcher behind ``difflib.unified_diff``, so the ranges are the
    head side of the 0-context diff. EC-07: a pure deletion has no head line,
    so it is anchored to the head line just after it (the last head line at
    end of file); with an empty head there is no range.
    """
    b, h = split_lines(base), split_lines(head)
    ranges: list[tuple[int, int]] = []
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(None, b, h).get_opcodes():
        if tag in ("replace", "insert"):
            ranges.append((j1 + 1, j2))
        elif tag == "delete" and h:
            anchor = min(j1 + 1, len(h))
            ranges.append((anchor, anchor))
    return _merge(ranges)


# ---------------------------------------------------------------------------
# Content fetch and expanded diff (spec §8.3 step 1, §11)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Blob:
    content: bytes | None = None
    unavailable: str | None = None


_MISSING = _Blob()  # a side that is not fetched (added base, removed head)


def _fetch(client: GitHubClient, path: str, ref: str) -> _Blob:
    try:
        content = client.get_content_bytes(path, ref)
    except ForbiddenCall:
        # The guard refused this repository path and nothing was sent. The file
        # is listed by name only; the run is not failed for it.
        return _Blob(unavailable=UNAVAILABLE_UNSAFE_PATH)
    if content is None:
        return _Blob(unavailable=UNAVAILABLE_NOT_FOUND)
    return _Blob(content=content)


def _decode(blob: _Blob) -> str:
    return (blob.content or b"").decode("utf-8", errors="replace")


def _is_binary(blob: _Blob) -> bool:
    return blob.content is not None and b"\x00" in blob.content[:NUL_SCAN_BYTES]


def _validated_merge_base(client: GitHubClient, pull: PullRequest) -> str:
    sha = client.compare(pull.base_sha, pull.head_sha).merge_base_sha
    if not _SHA_RE.fullmatch(sha):
        raise GitHubApiError("malformed response: merge base is not a commit SHA")
    return sha


def expanded_diff(
    client: GitHubClient,
    pull: PullRequest,
    classification: Classification,
    *,
    client_factory: Callable[[], GitHubClient],
    max_workers: int = MAX_WORKERS,
) -> DiffContext:
    """Fetch the reviewed files' blobs and build the expanded diff.

    ``client`` reads the merge base. ``client_factory`` builds one client per
    worker thread for the blob fetches (``requests.Session`` is not
    documented as thread-safe).
    """
    if not isinstance(max_workers, int) or not 1 <= max_workers <= MAX_WORKERS:
        raise ValueError(f"max_workers must be in 1..{MAX_WORKERS}")
    reviewed = classification.reviewed
    total = changed_lines(classification)
    if not reviewed:
        return DiffContext(pull.head_sha, None, total, (), classification.name_only)

    merge_base = _validated_merge_base(client, pull)

    # (file index, side) -> (path, ref). Base is skipped for added files and
    # for files whose previous name is name-only (withheld), head for removed
    # ones; renamed files read the base at previous_filename.
    withheld = [base_withheld_reason(f) for f in reviewed]
    jobs: list[tuple[int, str, str, str]] = []
    for i, f in enumerate(reviewed):
        if f.status != "added" and withheld[i] is None:
            jobs.append((i, "base", f.previous_filename or f.filename, merge_base))
        if f.status != "removed":
            jobs.append((i, "head", f.filename, pull.head_sha))

    blobs = _fetch_all(jobs, client_factory, max_workers)

    files: list[FileDiff] = []
    late: list[NameOnlyFile] = []
    for i, f in enumerate(reviewed):
        base_blob = blobs.get((i, "base"), _MISSING)
        head_blob = blobs.get((i, "head"), _MISSING)
        unavailable = base_blob.unavailable or head_blob.unavailable
        if unavailable is not None:
            late.append(NameOnlyFile(f.filename, f.status, "content_unavailable", unavailable))
            continue
        if _is_binary(base_blob) or _is_binary(head_blob):
            late.append(NameOnlyFile(f.filename, f.status, "binary"))
            continue
        base_text, head_text = _decode(base_blob), _decode(head_blob)
        removed = f.status == "removed"
        # A withheld base diffs as added: empty base, every head line "+".
        diff_status = "added" if withheld[i] is not None else f.status
        files.append(
            FileDiff(
                filename=f.filename,
                status=f.status,
                previous_filename=f.previous_filename,
                diff=unified_diff(
                    f.previous_filename or f.filename, f.filename, base_text, head_text, diff_status
                ),
                head_content=None if removed else head_text,
                changed_ranges=() if removed else changed_ranges(base_text, head_text),
                base_withheld=withheld[i],
            )
        )

    return DiffContext(
        head_sha=pull.head_sha,
        merge_base_sha=merge_base,
        changed_lines=total,
        files=tuple(files),
        name_only=classification.name_only + tuple(late),
    )


def _fetch_all(
    jobs: list[tuple[int, str, str, str]],
    client_factory: Callable[[], GitHubClient],
    max_workers: int,
) -> dict[tuple[int, str], _Blob]:
    local = threading.local()

    def worker_client() -> GitHubClient:
        client: GitHubClient | None = getattr(local, "client", None)
        if client is None:
            client = client_factory()
            local.client = client
        return client

    def run(path: str, ref: str) -> _Blob:
        return _fetch(worker_client(), path, ref)

    results: dict[tuple[int, str], _Blob] = {}
    with ThreadPoolExecutor(
        max_workers=min(max_workers, len(jobs)), thread_name_prefix="code-review-fetch"
    ) as pool:
        futures: list[tuple[tuple[int, str], Future[_Blob]]] = [
            ((i, side), pool.submit(run, path, ref)) for i, side, path, ref in jobs
        ]
        try:
            for key, future in futures:
                results[key] = future.result()
        except BaseException:
            for _key, future in futures:
                future.cancel()
            raise
    return results


def diff_context(
    client: GitHubClient,
    pull: PullRequest,
    pull_files: PullFiles,
    max_diff_lines: int,
    *,
    client_factory: Callable[[], GitHubClient],
    max_workers: int = MAX_WORKERS,
) -> DiffContext | OverBudget:
    """Classify, size-check, and (within budget) build the expanded diff."""
    classification = classify(pull_files.files)
    over = check_size(classification, max_diff_lines, truncated=pull_files.truncated)
    if over is not None:
        return over
    return expanded_diff(
        client, pull, classification, client_factory=client_factory, max_workers=max_workers
    )
