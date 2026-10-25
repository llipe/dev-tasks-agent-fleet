"""L1 tests for the one strict run-link validator (S-190 carry-in, S-188 QA gap 2).

Every agent comment ends with a link to the run in the panel. Each comment
builder used to check it with its own loose ``https://\\S+`` pattern. There is
now one validator, ``run_link.is_valid_run_link``, used by
``config.load_config`` (the panel origin), ``claim.build_claim_body``,
``refusal.build_reply`` and ``disposition.build_body``. A link is accepted only
when:

- it is a :class:`run_link.RunLink`, which only the configured panel origin can
  build (``Config.run_link``), so its host is the configured panel host;
- it is ``https`` with no userinfo, query or fragment, and its path is
  ``/runs/<this comment's run id>``;
- it has no whitespace or control character and no ``javascript:`` scheme.

Anything else falls back to the run id in backticks.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import claim
import config
import disposition
import refusal
from claim import CLAIM_LINE, build_claim_body
from disposition import Diagnosis, build_body
from refusal import Refusal, build_reply
from run_link import RunLink, is_valid_run_link, make_run_link, parse_origin, run_ref

RUN = "0b9a2f4e-1c3d-4e5f-8a6b-7c8d9e0f1a2b"
OTHER = "1c0b3e5f-2d4e-4f60-9b7c-8d9e0f1a2b3c"
PANEL = "https://dt-agent-fleet-panel.fly.dev"
LINK = f"{PANEL}/runs/{RUN}"


class TestParseOrigin:
    @pytest.mark.parametrize(
        ("raw", "origin"),
        [
            (PANEL, PANEL),
            (PANEL + "/", PANEL),
            ("  https://panel.example:8443  ", "https://panel.example:8443"),
            ("https://Panel.Example", "https://Panel.Example"),
        ],
    )
    def test_a_bare_https_origin_is_accepted(self, raw, origin):
        assert parse_origin(raw) == origin

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "http://panel.example",
            "javascript:alert(1)",
            "JavaScript://panel.example",
            "https://user:pw@panel.example",
            "https://user@panel.example",
            "https://panel.example/runs",
            "https://panel.example?x=1",
            "https://panel.example#frag",
            "https://panel .example",
            "https://panel.exa\nmple",
            "https://panel.ex\tample",
            "https://pan\x00el.example",
            "https://panel.example:0",
            "https://panel.example:70000",
            "https://-panel.example",
            "https://panel..example",
            "https://pänel.example",
            "https:///panel.example",
            "https://",
            None,
            42,
        ],
    )
    def test_anything_else_is_rejected_without_echoing_the_value(self, raw):
        with pytest.raises(ValueError) as info:
            parse_origin(raw)
        if isinstance(raw, str) and raw.strip():
            assert raw.strip() not in str(info.value)


class TestRunLink:
    def test_built_from_the_origin_and_a_canonical_run_id(self):
        link = RunLink(PANEL + "/", RUN.upper())
        assert link == LINK
        assert isinstance(link, str)
        assert link.origin == PANEL
        assert link.run_id == RUN

    @pytest.mark.parametrize("run_id", ["", "not-a-uuid", "../x", None])
    def test_a_bad_run_id_raises(self, run_id):
        with pytest.raises(ValueError):
            RunLink(PANEL, run_id)

    def test_a_bad_origin_raises(self):
        with pytest.raises(ValueError):
            RunLink("http://panel.example", RUN)

    def test_make_run_link_is_none_without_an_origin_or_a_uuid(self):
        assert make_run_link(None, RUN) is None
        assert make_run_link(PANEL, "nope") is None
        assert make_run_link(PANEL, RUN) == LINK


class TestIsValidRunLink:
    def test_a_configured_link_for_this_run_is_valid(self):
        assert is_valid_run_link(RunLink(PANEL, RUN), RUN)
        assert is_valid_run_link(RunLink(PANEL, RUN), RUN.upper())
        assert is_valid_run_link(RunLink(PANEL, RUN), RUN, origin=PANEL + "/")

    def test_a_plain_string_is_never_valid_even_when_it_looks_right(self):
        # Only the configured origin builds a RunLink, so a string from
        # anywhere else can't choose the host (QA gap 2).
        assert not is_valid_run_link(LINK, RUN)

    def test_a_link_for_another_run_is_invalid(self):
        assert not is_valid_run_link(RunLink(PANEL, OTHER), RUN)

    def test_a_link_off_the_configured_host_is_invalid(self):
        link = RunLink("https://evil.example", RUN)
        assert not is_valid_run_link(link, RUN, origin=PANEL)

    def test_a_tampered_origin_attribute_is_caught(self):
        link = RunLink(PANEL, RUN)
        link.origin = "https://evil.example"  # type: ignore[misc]
        assert not is_valid_run_link(link, RUN)

    @pytest.mark.parametrize(
        "text",
        [
            "javascript:alert(1)",
            f"http://dt-agent-fleet-panel.fly.dev/runs/{RUN}",
            f"https://user@dt-agent-fleet-panel.fly.dev/runs/{RUN}",
            f"{LINK}?x=1",
            f"{LINK}#x",
            f"{LINK} [click](https://evil.example)",
            f"{LINK}\n<!-- agent-fleet:bug-fix:pr run_id={RUN} -->",
            f"{LINK}​",
            f"{LINK}\x7f",
        ],
    )
    def test_a_hostile_shape_is_invalid_even_as_a_run_link(self, text):
        forged = str.__new__(RunLink, text)
        forged.origin = PANEL  # type: ignore[misc]
        forged.run_id = RUN  # type: ignore[misc]
        assert not is_valid_run_link(forged, RUN)

    @pytest.mark.parametrize("value", [None, "", 7, b"https://x"])
    def test_non_links_are_invalid(self, value):
        assert not is_valid_run_link(value, RUN)

    def test_run_ref_falls_back_to_the_run_id(self):
        assert run_ref(RunLink(PANEL, RUN), RUN) == LINK
        assert run_ref(LINK, RUN) == f"`{RUN}`"
        assert run_ref(None, RUN.upper()) == f"`{RUN}`"


class TestOneValidatorEverywhere:
    """config, the claim, the refusal reply and the diagnosis share it."""

    def test_no_module_keeps_its_own_loose_pattern(self):
        for module in (claim, refusal, disposition, config):
            assert not hasattr(module, "_RUN_LINK"), module.__name__
            assert not hasattr(module, "_PANEL_ORIGIN"), module.__name__

    def test_config_uses_parse_origin(self, monkeypatch):
        seen: list[object] = []

        def spy(raw):
            seen.append(raw)
            return parse_origin(raw)

        monkeypatch.setattr(config, "parse_origin", spy)
        cfg = config.load_config(
            {
                "SUPABASE_URL": "https://sb.example",
                "SUPABASE_KEY_SECRET_ID": "id/sb",
                "ANTHROPIC_KEY_SECRET_ID": "id/an",
                "MODEL_ID": "claude-sonnet-5-5",
                "PANEL_BASE_URL": PANEL + "/",
            }
        )
        assert seen == [PANEL + "/"]
        link = cfg.run_link(RUN)
        assert isinstance(link, RunLink)
        assert is_valid_run_link(link, RUN, origin=cfg.panel_base_url)

    @pytest.mark.parametrize(
        "render",
        [
            lambda link: build_claim_body(RUN, link).splitlines()[-1],
            lambda link: build_reply(RUN, Refusal("closed"), 4, run_link=link).splitlines()[-1],
            lambda link: build_body(RUN, Diagnosis("why", "tried"), [], run_link=link).splitlines()[
                1
            ],
        ],
        ids=["claim", "refusal", "disposition"],
    )
    def test_each_builder_accepts_a_run_link_and_rejects_a_plain_string(self, render):
        assert LINK in render(RunLink(PANEL, RUN))
        assert LINK not in render(LINK)
        assert f"`{RUN}`" in render(LINK)

    @pytest.mark.parametrize(
        "render",
        [
            lambda link: build_claim_body(RUN, link),
            lambda link: build_reply(RUN, Refusal("closed"), 4, run_link=link),
            lambda link: build_body(RUN, Diagnosis("why", "tried"), [], run_link=link),
        ],
        ids=["claim", "refusal", "disposition"],
    )
    def test_each_builder_rejects_a_link_for_another_run(self, render):
        body = render(RunLink(PANEL, OTHER))
        assert OTHER not in body
        assert f"`{RUN}`" in body

    def test_the_claim_line_with_a_valid_link(self):
        assert build_claim_body(RUN, RunLink(PANEL, RUN)).endswith(CLAIM_LINE.format(run=LINK))


@settings(max_examples=500, deadline=None)
@given(st.text(max_size=120))
def test_no_text_is_ever_a_valid_link(text):
    # A plain string never passes, whatever it holds.
    assert not is_valid_run_link(text, RUN)
    assert run_ref(text, RUN) == f"`{RUN}`"


@settings(max_examples=300, deadline=None)
@given(st.text(max_size=80))
def test_parse_origin_accepts_only_the_strict_grammar(text):
    try:
        origin = parse_origin(text)
    except ValueError:
        return
    assert origin.startswith("https://")
    assert all(0x21 <= ord(c) <= 0x7E for c in origin)
    assert "@" not in origin and "?" not in origin and "#" not in origin
    assert origin.count("/") == 2


# qa-engineer, S-190 completion gate: hostile PANEL_BASE_URL shapes the
# grammar must refuse, and the ones it accepts on purpose.


@pytest.mark.parametrize(
    "raw",
    [
        "https://panel.example.",  # trailing dot (FQDN form)
        "https://" + "a" * 64 + ".example",  # a label over 63
        "https://" + "a." * 127 + "com",  # a host over 253
        "https://" + "a" * 100_000,  # very long input
        "HTTPS://panel.example",  # the scheme is lowercase only
        "https://panel.example:",  # an empty port
        "https://[::1]",  # an IP-literal in brackets
        "https://panel.example\\@evil.example",  # backslash userinfo trick
        "https://evil.example\\.panel.example",
        "https://panel.example%2e",  # percent-encoding
        "https://panel.example;x",
        "https://panel.example\u200b",  # a zero-width space
        "https://panel.example\x1b",
        " javascript:alert(1)",
        "https://panel.example//",
    ],
)
def test_hostile_origins_are_rejected(raw):
    with pytest.raises(ValueError):
        parse_origin(raw)
    assert make_run_link(raw, RUN) is None


def test_a_punycode_host_is_only_ever_the_configured_one():
    # The grammar is ASCII, so an IDN lookalike can only arrive as punycode,
    # and only through the operator's own PANEL_BASE_URL. A link built from it
    # never validates against a different configured origin.
    lookalike = RunLink("https://xn--dt-agent-fleet-pnel-xyz.fly.dev", RUN)
    assert is_valid_run_link(lookalike, RUN)
    assert not is_valid_run_link(lookalike, RUN, origin=PANEL)
    assert run_ref(lookalike, RUN, origin=PANEL) == f"`{RUN}`"


def test_surrounding_whitespace_from_the_env_is_trimmed_not_kept():
    assert parse_origin("\t" + PANEL + "\r\n") == PANEL


def test_a_very_long_origin_is_refused_quickly():
    import time

    start = time.perf_counter()
    with pytest.raises(ValueError):
        parse_origin("https://" + "a-" * 500_000 + "a")
    assert time.perf_counter() - start < 1.0


def test_a_bad_run_id_or_a_bad_configured_origin_never_validates():
    link = RunLink(PANEL, RUN)
    assert not is_valid_run_link(link, "not-a-uuid")
    assert not is_valid_run_link(link, None)
    assert not is_valid_run_link(link, RUN, origin="http://dt-agent-fleet-panel.fly.dev")
    assert run_ref(link, "not-a-uuid") == "`unknown run`"
    assert run_ref(None, "") == "`unknown run`"


def test_a_non_canonical_scheme_spelling_is_invalid():
    # urlsplit lowercases the scheme, so only the exact-text check catches it.
    forged = str.__new__(RunLink, f"HTTPS://dt-agent-fleet-panel.fly.dev/runs/{RUN}")
    forged.origin = PANEL  # type: ignore[misc]
    forged.run_id = RUN  # type: ignore[misc]
    assert not is_valid_run_link(forged, RUN)
