"""
QA-PRD-02: a secret split by invisible characters is scrubbed before any write.

``scrubber.scrub`` (vendored, shared with the siblings) matches the exact
secret only. Model or repository text can hide a secret behind the characters
``render.neutralize`` drops (zero-width characters, the word joiner, the BOM,
the tag block, bidi controls): any viewer that drops them shows the secret.
``render.strip_invisible`` is that one shared set, and the pipeline's scrub of
model and repository text removes it before scrubbing whenever doing so
reveals a secret. Text that hides no secret is returned unchanged, so a
canonical path keeps its characters in the artifact.
"""

from __future__ import annotations

import dataclasses
from typing import Any, cast

import pytest

import render
from pipeline import _scrub_name_only, _scrub_text, _scrub_validation, scrub_value
from render import neutralize, strip_invisible

SECRET = "ghs_INSTALLATIONtokenSENTINEL0123456789"
OTHER = "svc-key-SENTINEL-5b1e9c"

# What the task and the render module docstring name, plus the bidi controls
# neutralize also drops.
NAMED = (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0xE0000, 0xE0041, 0xE007F)
BIDI = (0x061C, 0x200E, 0x200F, 0x202A, 0x202E, 0x2066, 0x2069)


@pytest.mark.parametrize("cp", NAMED + BIDI, ids=lambda cp: f"U+{cp:04X}")
def test_strip_invisible_drops_what_neutralize_drops(cp):
    c = chr(cp)
    assert strip_invisible(f"a{c}b") == "ab"
    assert neutralize(f"a{c}b") == "ab"


def test_strip_invisible_is_exactly_the_set_neutralize_drops():
    """Over the BMP and the tag block: a character neutralize removes outright is
    one strip_invisible removes, and no other (one shared set, not a second list)."""
    for cp in (*range(0x10000), *range(0xE0000, 0xE0100)):
        if 0xD800 <= cp <= 0xDFFF:
            continue
        c = chr(cp)
        dropped_by_neutralize = neutralize(f"a{c}b") == "ab"
        assert (strip_invisible(c) == "") is dropped_by_neutralize, f"U+{cp:04X}"


@pytest.mark.parametrize(
    "kept",
    [" ", "\t", "️", "­", "\U0001f600", "a b", "\\", "`"],
    ids=repr,
)
def test_strip_invisible_keeps_what_neutralize_does_not_drop(kept):
    assert strip_invisible(kept) == kept


def test_strip_invisible_uses_the_render_set():
    assert render.strip_invisible("​") == ""
    assert "strip_invisible" in render.__all__


def _split(secret: str, sep: str = "​") -> str:
    return sep.join(secret)


@pytest.mark.parametrize("sep", ["​", "⁠", "﻿", "\U000e0020", "‎"])
def test_a_split_secret_is_scrubbed(sep):
    assert _scrub_text(f"uses {_split(SECRET, sep)} here", [SECRET]) == "uses *** here"


def test_a_raw_secret_is_scrubbed_as_before():
    assert _scrub_text(f"a {SECRET} b {OTHER}", [SECRET, OTHER]) == "a *** b ***"


def test_text_hiding_no_secret_is_unchanged():
    """A path with a zero-width character keeps it: only a revealed secret changes text."""
    for text in ("src/we​ird.py", "a​b", "​", "", "plain"):
        assert _scrub_text(text, [SECRET, OTHER]) == text


def test_a_split_and_a_raw_secret_in_one_text():
    out = _scrub_text(f"{SECRET} and {_split(OTHER)}", [SECRET, OTHER])
    assert out == "*** and ***"


def test_empty_secrets_are_ignored():
    assert _scrub_text("a​b", ["", SECRET]) == "a​b"
    assert _scrub_text("a​b", []) == "a​b"


def test_scrub_value_reaches_nested_split_secrets():
    """Every reporter write goes through scrub_value: events, metrics, the artifact."""
    value = {
        "title": f"uses {_split(SECRET)}",
        _split(OTHER): [f"x {_split(OTHER)}", ("t", _split(SECRET))],
        "n": 3,
    }
    assert scrub_value(value, [SECRET, OTHER]) == {
        "title": "uses ***",
        "***": ["x ***", ["t", "***"]],
        "n": 3,
    }


def test_the_pre_render_scrub_of_findings_and_name_only_files_is_invisible_aware():
    from context.diff import NameOnlyFile
    from validate import Validation

    @dataclasses.dataclass(frozen=True)
    class F:
        file: str
        title: str
        failure_scenario: str
        consequence: str

    f = F("src/a\u200bb.py", f"uses {_split(SECRET)}", _split(OTHER), "c")
    v = Validation(
        verdict="blocking",
        blocking=(cast(Any, f),),
        suggestions=(),
        dropped=(),
        candidates=(),
        counts=cast(Any, None),
    )
    (g,) = _scrub_validation(v, [SECRET, OTHER]).blocking
    assert (g.file, g.title, g.failure_scenario, g.consequence) == (
        "src/a\u200bb.py",
        "uses ***",
        "***",
        "c",
    )

    nf = NameOnlyFile(f"{_split(SECRET)}.lock", "added", "lockfile", _split(OTHER))
    (out,) = _scrub_name_only([nf], [SECRET, OTHER])
    assert (out.filename, out.detail) == ("***.lock", "***")
