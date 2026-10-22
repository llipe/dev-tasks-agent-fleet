"""
S-207 AC5 — spec trimming (TC-207-17..20; spec §8.3 step 3, D-24).

A spec over 30% of ``max_context_tokens`` keeps (i) the heading outline,
(ii) the sections cited as ``Spec §<n>[.<m>…]`` in an issue body (dotted-prefix
match on the heading number, with the cited section's sub-headings), and
(iii) the sections whose heading or text names a linked story ID or a reviewed
path; then it is truncated to 30% if still over.
"""

from __future__ import annotations

import pytest

from context.issues import LinkedIssue
from context.spec import spec_cap, spec_citations, story_ids, trim_spec
from context.tokens import TRUNCATION_MARKER, estimate

FILLER = "lorem ipsum dolor sit amet " * 40 + "\n"

SPEC = (
    "# Spec\n"
    "Preamble text.\n"
    "## 1. Intro\n" + FILLER + "## 8. Business Logic\n"
    "eight intro\n"
    "### 8.1 Routing\n"
    "routing body\n"
    "#### Notes\n"
    "routing notes\n"
    "### 8.10 Ten\n"
    "ten body\n"
    "### 8.2 Resolution\n"
    "resolution body mentions S-170.\n"
    "## 80. Eighty\n"
    "eighty body\n"
    "## 9. Paths\n"
    "Touches `panel/lib/domain/webhook-routing.ts`.\n"
    "## 10. Other\n" + FILLER + "```bash\n"
    "# not a heading inside a fence\n"
    "```\n"
)

# Below the whole spec, above any selection the tests make.
TRIM_CAP = 300
assert estimate(SPEC) > TRIM_CAP

OUTLINE = [
    "# Spec\n",
    "## 1. Intro\n",
    "## 8. Business Logic\n",
    "### 8.1 Routing\n",
    "#### Notes\n",
    "### 8.10 Ten\n",
    "### 8.2 Resolution\n",
    "## 80. Eighty\n",
    "## 9. Paths\n",
    "## 10. Other\n",
]


def _trim(text=SPEC, *, citations=(), ids=(), paths=(), cap=50):
    return trim_spec(text, citations=citations, story_ids=ids, reviewed_paths=paths, cap_tokens=cap)


def _issue(title: str = "t", body: str = "") -> LinkedIssue:
    return LinkedIssue(1, title, (), body, body, False, False)


# -- TC-207-17: within the cap ----------------------------------------------


def test_spec_within_30_percent_is_passed_whole():
    out = _trim(cap=estimate(SPEC))
    assert out == (SPEC, False, False)


def test_spec_cap_is_30_percent_of_max_context_tokens():
    assert spec_cap(150_000) == 45_000
    assert spec_cap(20_001) == 6_000


# -- TC-207-18: over the cap -------------------------------------------------


def test_over_the_cap_keeps_outline_citations_story_ids_and_paths():
    text, trimmed, truncated = _trim(
        citations=("8.1",),
        ids=("S-170",),
        paths=("panel/lib/domain/webhook-routing.ts",),
        cap=TRIM_CAP,
    )
    assert (trimmed, truncated) == (True, False)
    for heading in OUTLINE:
        assert heading in text
    assert "routing body" in text and "routing notes" in text  # cited, with sub-headings
    assert "resolution body mentions S-170." in text  # story ID
    assert "Touches `panel/lib/domain/webhook-routing.ts`." in text  # reviewed path
    for excluded in ("lorem", "eight intro", "ten body", "eighty body", "Preamble"):
        assert excluded not in text
    assert "not a heading inside a fence" not in text


def test_kept_lines_follow_document_order():
    text, _, _ = _trim(citations=("8.1",), cap=TRIM_CAP)
    lines = text.splitlines(keepends=True)
    assert lines == [
        "# Spec\n",
        "## 1. Intro\n",
        "## 8. Business Logic\n",
        "### 8.1 Routing\n",
        "routing body\n",
        "#### Notes\n",
        "routing notes\n",
        "### 8.10 Ten\n",
        "### 8.2 Resolution\n",
        "## 80. Eighty\n",
        "## 9. Paths\n",
        "## 10. Other\n",
    ]


def test_story_id_matches_whole_ids_only():
    text, _, _ = _trim(ids=("S-17",), cap=TRIM_CAP)
    assert "resolution body" not in text


def test_section_named_in_its_heading_is_kept():
    spec = "# T\n## 3. S-209 budget\nbudget body\n## 4. Other\n" + FILLER
    text, trimmed, _ = _trim(spec, ids=("S-209",), cap=60)
    assert trimmed and "budget body" in text and "lorem" not in text


def test_preamble_naming_a_path_is_kept():
    spec = "Intro names src/app.py here.\n# T\n" + FILLER
    text, _, _ = _trim(spec, paths=("src/app.py",), cap=60)
    assert text == "Intro names src/app.py here.\n# T\n"


# -- TC-207-19: dotted-prefix matching ---------------------------------------


def test_spec_8_keeps_8_and_its_subsections_but_not_80():
    text, _, _ = _trim(citations=("8",), cap=TRIM_CAP)
    for body in ("eight intro", "routing body", "routing notes", "ten body", "resolution body"):
        assert body in text
    assert "eighty body" not in text


def test_spec_8_1_keeps_8_1_but_not_8_10():
    text, _, _ = _trim(citations=("8.1",), cap=TRIM_CAP)
    assert "routing body" in text
    assert "ten body" not in text
    assert "eight intro" not in text


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("see Spec §8.1 here", ("8.1",)),
        ("Spec §8, Spec §8.3.2.", ("8", "8.3.2")),
        ("Spec§4 and Spec  § 5", ("4", "5")),
        ("spec §8.1", ()),  # case-sensitive "Spec", as in the convention
        ("§8.1 alone", ()),
        ("Spec §x", ()),
        ("Spec §8.1 twice Spec §8.1", ("8.1",)),
    ],
)
def test_spec_citations(body, expected):
    assert spec_citations([_issue(body=body)]) == expected


def test_story_ids_come_from_linked_issue_titles():
    issues = [
        _issue(title="[PRD-webhook-triggers] Story S-170: pure routing engine"),
        _issue(title="[PRD-x] Story S-9: y"),
        _issue(title="fix: S-1 mentioned but not a story title"),
        _issue(title="[PRD-x] Story S-170: dup"),
    ]
    assert story_ids(issues) == ("S-170", "S-9")


# -- TC-207-20: still over after selection → truncated -----------------------


def test_still_over_after_selection_is_truncated_within_the_cap():
    big_cited = "# T\n## 8. Big\n" + FILLER * 20 + "## 9. Other\n" + FILLER
    cap = 200
    text, trimmed, truncated = _trim(big_cited, citations=("8",), cap=cap)
    assert trimmed and truncated
    assert estimate(text) <= cap
    assert text.endswith(TRUNCATION_MARKER + "\n")
    assert text.startswith("# T\n## 8. Big\n")


def test_tiny_cap_still_never_exceeds_it():
    for cap in (0, 1, 3, 5):
        text, trimmed, truncated = _trim(cap=cap)
        assert estimate(text) <= cap
        assert trimmed and truncated


def test_trimming_happens_through_resolve_when_over_the_share():
    from context.spec import resolve_specs
    from github_client import GitHubClient
    from tests.helpers.github_stub import StubTransport, text_response

    stub = StubTransport(
        {
            (
                "GET",
                "/repos/acme/widgets/contents/workstream/specification-prd-x.md",
            ): text_response(SPEC * 200)
        }
    )
    client = GitHubClient("ghs_t", "acme", "widgets", 42, transport=stub, sleep=lambda _s: None)
    ctx = resolve_specs(
        client,
        [_issue(title="[PRD-x] Story S-170: t", body="Spec §8.1")],
        "9f2c4e1a7b3d5f60812a4c6e8b0d2f4a6c8e0b1d",
        reviewed_paths=(),
        max_context_tokens=20_000,
    )
    spec = ctx.spec
    assert spec is not None
    assert spec.trimmed is True
    assert spec.tokens == estimate(SPEC * 200)
    assert estimate(spec.text) <= spec_cap(20_000)
    assert ctx.citations == ("8.1",) and ctx.story_ids == ("S-170",)


def test_two_specs_share_the_cap_equally():
    from context.spec import resolve_specs
    from github_client import GitHubClient
    from tests.helpers.github_stub import StubTransport, text_response

    base = "/repos/acme/widgets/contents/workstream/"
    stub = StubTransport(
        {
            ("GET", base + "specification-prd-a.md"): text_response(SPEC * 200),
            ("GET", base + "specification-prd-b.md"): text_response(SPEC * 200),
        }
    )
    client = GitHubClient("ghs_t", "acme", "widgets", 42, transport=stub, sleep=lambda _s: None)
    ctx = resolve_specs(
        client,
        [_issue(title="[PRD-a] t"), _issue(title="[PRD-b] u")],
        "9f2c4e1a7b3d5f60812a4c6e8b0d2f4a6c8e0b1d",
        reviewed_paths=(),
        max_context_tokens=20_000,
    )
    assert len(ctx.specs) == 2
    assert sum(estimate(s.text) for s in ctx.specs) <= spec_cap(20_000)
    assert all(estimate(s.text) <= spec_cap(20_000) // 2 for s in ctx.specs)
