"""
PRD v1.5 FR-5 — full files are for code files, and they come before the spec (D-67).

A reviewed documentation file (a documentation extension, or under ``docs/``)
reaches the model as its ±50-line diff only: no full copy, and it is neither
"included" nor "dropped" as a full file. Source and test files get their whole
head content, placed right after the drift sections and before the spec and the
conventions, so a large spec is trimmed before a complete code file is dropped.
"""

from __future__ import annotations

import pytest

from bedrock_adapter import WARN_CONTEXT_NO_FILES, WARN_CONTEXT_RETRY, BedrockError
from budget import BLOCK_FILE
from prompt import LABEL_FILE, Prompt, build_prompt
from tests.fixtures.bedrock import (
    FakeConverse,
    context_length_rejected,
    tool_use_response,
    valid_review,
)
from tests.helpers.bedrock_run import Recorder, first_prompt, review_inputs, run
from tests.helpers.prompt_inputs import (
    NONCE,
    candidate,
    conventions_ctx,
    diff_ctx,
    file_diff,
    inputs,
    parse_blocks,
    report,
    spec,
    spec_ctx,
    verifier_ctx,
)

BIG = 10_000_000
DOCS = ("README.md", "docs/guide.py", "workstream/notes.rst")


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


def test_the_retry_drops_only_code_files():
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
    # Files follow the drift sections (d). The file fits the remainder alone, but
    # not after the drift section: the section is placed whole and the file is
    # dropped. Filling the file first would cut the section instead.
    rep = report(section="## Drift\n" + _text(2_500, "d"), candidates=[candidate(1)])
    code = file_diff("src/app.py", head=_text(28_500, "c"))
    ins = inputs(verifier=verifier_ctx(rep), diff=diff_ctx([code]))
    base = _build(ins, include_full_files=False).context.mandatory_tokens
    p = _build(ins, base + 30_000)
    (sec,) = [c for k, _, c in parse_blocks(p.user, p.nonce)[0] if k == "verifier"]
    assert sec == rep.section
    assert p.context.full_files_dropped == ("src/app.py",)


def test_a_docs_only_pr_has_no_full_file_and_no_full_file_note():
    # With no code file there is nothing to include, drop, or mention, with or
    # without full files (the R4 retry and repair rebuild).
    for kw in ({}, {"include_full_files": False}):
        p = _build(review_inputs(DOCS), **kw)
        assert p.context.full_files_included == () and p.context.full_files_dropped == ()
        assert LABEL_FILE not in p.user and "full files" not in p.user


def test_a_docs_only_pr_is_not_retried_on_context_length():
    # R4 removes full files; a docs-only PR has none, so there is no retry.
    rec = Recorder()
    fake = FakeConverse([context_length_rejected()])
    with pytest.raises(BedrockError):
        run(fake, review_inputs(DOCS), recorder=rec)
    assert fake.calls == 1
    assert rec.messages == [WARN_CONTEXT_NO_FILES]


def test_the_context_length_retry_counts_and_notes_code_files_only():
    ins = review_inputs(("src/a.py", *DOCS))
    p = first_prompt(ins)
    assert p.context.full_files_included == ("src/a.py",)
    rec = Recorder()
    run(
        FakeConverse([context_length_rejected(), tool_use_response(valid_review())]),
        ins,
        prompt=p,
        recorder=rec,
    )
    (retry,) = rec.prompts
    assert retry.context.full_files_dropped == ("src/a.py",)
    assert "- 1 full files are not included (budget)" in retry.user
    assert dict(rec.warns)[WARN_CONTEXT_RETRY]["files"] == 1
