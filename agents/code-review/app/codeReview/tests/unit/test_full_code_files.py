"""
PRD v1.5 FR-5 — full files are for code files, and they come before the spec (D-67).

A reviewed documentation file (a documentation extension, or under ``docs/``)
reaches the model as its ±50-line diff only: no full copy, and it is neither
"included" nor "dropped" as a full file. Source and test files get their whole
head content, placed right after the drift sections and before the spec and the
conventions, so a large spec is trimmed before a complete code file is dropped.
"""

from __future__ import annotations

from budget import BLOCK_FILE
from prompt import Prompt, build_prompt
from tests.helpers.prompt_inputs import (
    NONCE,
    conventions_ctx,
    diff_ctx,
    file_diff,
    inputs,
    parse_blocks,
    spec,
    spec_ctx,
)

BIG = 10_000_000


def _text(tokens: int, tag: str = "x") -> str:
    line = (tag * 34)[:34] + "\n"
    return line * max(1, (tokens * 7 // 2) // len(line))


def _build(ins, max_context_tokens: int = BIG, **kw) -> Prompt:
    out = build_prompt(
        ins, max_context_tokens=max_context_tokens, max_diff_lines=2000, nonce=NONCE, **kw
    )
    assert isinstance(out, Prompt), out
    return out


def _file_paths(p: Prompt) -> list[str]:
    blocks, _ = parse_blocks(p.user, p.nonce)
    return [c.split("\n", 1)[0].removeprefix("path: ") for k, _, c in blocks if k == BLOCK_FILE]


def test_documentation_files_get_their_diff_only():
    files = [
        file_diff("src/app.py", head="code = 1\n"),
        file_diff("README.md", head="DOC-SENTINEL-1\n"),
        file_diff("docs/guide.py", head="DOC-SENTINEL-2\n"),
        file_diff("workstream/audit.md", head="DOC-SENTINEL-3\n"),
        file_diff("tests/test_app.py", head="test = 1\n"),
    ]
    p = _build(inputs(diff=diff_ctx(files)))
    assert _file_paths(p) == ["src/app.py", "tests/test_app.py"]
    assert p.context.full_files_included == ("src/app.py", "tests/test_app.py")
    assert p.context.full_files_dropped == ()
    # The docs are still reviewed: their diffs are in the diff block.
    blocks, _ = parse_blocks(p.user, p.nonce)
    diff = next(c for k, _, c in blocks if k == "diff")
    for name in ("README.md", "docs/guide.py", "workstream/audit.md"):
        assert name in diff


def test_a_docs_only_retry_leaves_nothing_to_drop():
    files = [file_diff("README.md"), file_diff("src/app.py")]
    p = _build(inputs(diff=diff_ctx(files)), include_full_files=False)
    assert p.context.full_files_dropped == ("src/app.py",)


def test_a_complete_code_file_is_kept_before_a_large_spec():
    code = file_diff("modules/offer/src/offer.facade.ts", head=_text(8_000, "c"))
    big_spec = spec(text=_text(80_000, "s"))
    ins = inputs(
        specs=spec_ctx(big_spec),
        conventions=conventions_ctx(_text(5_000, "k")),
        diff=diff_ctx([code]),
    )
    base = _build(ins, include_full_files=False).context.mandatory_tokens
    p = _build(ins, base + 12_000)
    assert p.context.full_files_included == ("modules/offer/src/offer.facade.ts",)
    spec_notes = [n for n in p.context.notes if n.block == "spec"]
    assert spec_notes and spec_notes[-1].reason == "budget"


def test_code_files_do_not_take_the_drift_sections_room():
    # Files follow the drift sections (d): with room for both, both are placed whole.
    from tests.helpers.prompt_inputs import candidate, report, verifier_ctx

    code = file_diff("src/app.py", head=_text(2_000, "c"))
    v = verifier_ctx(report(candidates=[candidate(1)]))
    p = _build(inputs(verifier=v, diff=diff_ctx([code])), 60_000)
    kinds = [k for k, _, _ in parse_blocks(p.user, p.nonce)[0]]
    assert "verifier" in kinds and "verifier-candidate" in kinds and "file" in kinds
