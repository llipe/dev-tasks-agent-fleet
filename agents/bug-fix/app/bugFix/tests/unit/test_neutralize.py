"""L1 tests for ``neutralize.py`` (S-186 AC4; D-65, D-85).

A closing keyword followed by an issue reference loses the keyword and keeps
the reference as ``(ref <reference>)``; for ``#N`` that is exactly ``(ref #N)``.
Every ``@`` is followed by U+200B, so no mention notifies anyone.
"""

from __future__ import annotations

import pytest

from neutralize import ZWSP, neutralize

KEYWORDS = [
    "close",
    "closes",
    "closed",
    "fix",
    "fixes",
    "fixed",
    "resolve",
    "resolves",
    "resolved",
]


class TestClosingKeywords:
    @pytest.mark.parametrize("kw", KEYWORDS)
    def test_each_keyword_with_hash_ref(self, kw):
        assert neutralize(f"This {kw} #42 now.") == "This (ref #42) now."

    @pytest.mark.parametrize("kw", ["FIXES", "Closes", "rEsOlVeD"])
    def test_case_insensitive(self, kw):
        assert neutralize(f"{kw} #1") == "(ref #1)"

    def test_optional_colon(self):
        assert neutralize("Fixes: #9") == "(ref #9)"

    def test_owner_repo_ref_keeps_the_reference(self):
        assert neutralize("closes o/r#1") == "(ref o/r#1)"
        assert neutralize("Fixes llipe/dev-tasks.agent_fleet#123") == (
            "(ref llipe/dev-tasks.agent_fleet#123)"
        )

    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/o/r/issues/5",
            "http://github.com/o/r/issues/5",
            "https://www.github.com/o/r/pull/7",
            "HTTPS://GITHUB.COM/O/R/ISSUES/5",
        ],
    )
    def test_issue_url(self, url):
        assert neutralize(f"resolves {url}") == f"(ref {url})"

    def test_gh_shorthand(self):
        assert neutralize("fixes GH-12") == "(ref GH-12)"

    def test_several_references(self):
        out = neutralize("Fixes #1 and closes #2, resolved o/r#3")
        assert out == "(ref #1) and (ref #2), (ref o/r#3)"

    def test_newline_between_keyword_and_reference(self):
        assert neutralize("fixes\n#4") == "(ref #4)"

    @pytest.mark.parametrize(
        "text",
        [
            "prefixes #1",  # keyword inside a longer word
            "fixture #1",
            "fixes the bug",  # no reference
            "fix#1",  # no whitespace
            "issue #1 is fixed",
            "see #1",
        ],
    )
    def test_non_closing_text_unchanged(self, text):
        assert neutralize(text) == text

    def test_keyword_exposed_by_a_previous_replacement(self):
        # Found by RT-12: "#1close" is not a closing keyword, but once the
        # first reference becomes "(ref #1)" it would be.
        assert neutralize("close #1close #1") == "(ref #1)(ref #1)"

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Fixes:#1", "(ref #1)"),
            ("closes:o/r#2", "(ref o/r#2)"),
            ("resolved:https://github.com/o/r/issues/3", "(ref https://github.com/o/r/issues/3)"),
            ("fixes:**#4**", "(ref **#4**)"),
        ],
    )
    def test_colon_with_no_whitespace(self, text, expected):
        # QA gap 3: GitHub accepts "Fixes:#1".
        assert neutralize(text) == expected

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            (
                "fixes [#1](https://github.com/o/r/issues/1)",
                "(ref [#1](https://github.com/o/r/issues/1))",
            ),
            ("Closes [o/r#2](u)", "(ref [o/r#2](u))"),
            ("fixes [#1]", "(ref [#1])"),
            ("fixes **#1**", "(ref **#1**)"),
            ("fixes *#1*", "(ref *#1*)"),
            ("fixes __#1__", "(ref __#1__)"),
            ("fixes `#1`", "(ref `#1`)"),
            ("fixes **#1", "(ref **#1)"),  # unclosed wrapper: still defused
            (
                "fixes <https://github.com/o/r/issues/1>",
                "(ref <https://github.com/o/r/issues/1>)",
            ),
            ("fixes github.com/o/r/issues/1", "(ref github.com/o/r/issues/1)"),
            ("resolves www.github.com/o/r/pull/2", "(ref www.github.com/o/r/pull/2)"),
            ("fixes <github.com/o/r/issues/1>", "(ref <github.com/o/r/issues/1>)"),
        ],
    )
    def test_markdown_wrapped_and_schemeless_references(self, text, expected):
        # QA gap 3: over-neutralizing only changes wording, so wrapped forms go too.
        out = neutralize(text)
        assert out == expected
        assert neutralize(out) == out

    def test_a_long_glued_chain_is_linear_not_quadratic(self):
        # Each replacement exposed one more glued keyword, one pass at a time:
        # 65,536 characters took ~14 s, beyond the 10 s SIGTERM budget.
        import time

        text = "close #1" * (65_536 // 8)
        start = time.perf_counter()
        out = neutralize(text)
        assert time.perf_counter() - start < 2.0
        assert out == "(ref #1)" * (65_536 // 8)

    def test_keyword_glued_to_underscore_is_still_neutralized(self):
        # Over-neutralizing is harmless; under-neutralizing closes an issue.
        assert neutralize("_fixes #1") == "_(ref #1)"


class TestMentions:
    def test_at_mention(self):
        assert neutralize("ping @octocat") == f"ping @{ZWSP}octocat"

    def test_team_mention_and_email(self):
        assert neutralize("@org/team a@b.c") == f"@{ZWSP}org/team a@{ZWSP}b.c"

    def test_already_neutralized_at_is_not_doubled(self):
        assert neutralize(f"@{ZWSP}octocat") == f"@{ZWSP}octocat"

    def test_mention_inside_closing_ref_text(self):
        assert neutralize("@bot fixes #3") == f"@{ZWSP}bot (ref #3)"


class TestMisc:
    def test_empty(self):
        assert neutralize("") == ""

    def test_idempotent_examples(self):
        for text in [
            "Fixes #1 @a",
            "closes o/r#1",
            "x@y",
            "fixes fixes #2",
            "fixes:fixes:#2",
            "fixes [fixes #1](u)",
            "fixes **fixes **#3****",
        ]:
            once = neutralize(text)
            assert neutralize(once) == once

    def test_crlf_preserved(self):
        assert neutralize("line one\r\nFixes #1\r\n") == "line one\r\n(ref #1)\r\n"

    def test_rejects_non_string(self):
        with pytest.raises(TypeError):
            neutralize(None)  # type: ignore[arg-type]
