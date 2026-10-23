"""L1 tests for the scrubber (TC-180-15, D-50, D-99, FR-34).

The sibling's ``scrub``/``scrub_process_error`` contract is kept, and the
bug-fix extensions are pinned here: the Anthropic API key, the GitHub App PEM,
the installation token and the Projects PAT are redacted from plain strings,
exception messages, nested structures and gate-output tails, whether or not
the value was registered.
"""

from __future__ import annotations

import json
import subprocess
import traceback

from hypothesis import given
from hypothesis import strategies as st

from scrubber import (
    REDACTED,
    SecretSet,
    redact_patterns,
    scrub,
    scrub_all,
    scrub_exception,
    scrub_obj,
    scrub_process_error,
    tail,
)

# Sentinels shaped like the real credentials, never real ones.
ANTHROPIC_KEY = "sk-ant-api03-" + "A1b2C3d4E5f6G7h8I9j0" * 4 + "-ZZtest"
PROJECTS_PAT = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"  # ghp_ + 36
INSTALL_TOKEN = "ghs_" + "Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4J3i2"  # ghs_ + 36
APP_PEM = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIEowIBAAKCAQEAsentinelsentinelsentinelsentinelsentinel\n"
    "c2VudGluZWxzZW50aW5lbHNlbnRpbmVsc2VudGluZWxzZW50aW5lbA==\n"
    "-----END RSA PRIVATE KEY-----"
)
SUPABASE_KEY = "supabase-service-role-sentinel-value"

ALL = [ANTHROPIC_KEY, PROJECTS_PAT, INSTALL_TOKEN, APP_PEM, SUPABASE_KEY]


def _registered() -> SecretSet:
    s = SecretSet()
    s.add("ANTHROPIC_API_KEY", ANTHROPIC_KEY)
    s.add("GITHUB_PROJECTS_TOKEN", PROJECTS_PAT)
    s.add("GITHUB_INSTALLATION_TOKEN", INSTALL_TOKEN)
    s.add("GITHUB_APP_PEM", APP_PEM)
    s.add("SUPABASE_SERVICE_ROLE_KEY", SUPABASE_KEY)
    return s


def _assert_clean(text: str) -> None:
    for secret in ALL:
        assert secret not in text
    # No fragment of the PEM body either.
    assert "sentinelsentinel" not in text
    assert "BEGIN RSA PRIVATE KEY" not in text


# ---------------------------------------------------------------------------
# Sibling contract (kept)
# ---------------------------------------------------------------------------


class TestSiblingContract:
    def test_scrub_replaces_known_secret(self):
        assert scrub("Bearer abc123", ["abc123"]) == f"Bearer {REDACTED}"

    def test_scrub_skips_empty_and_none(self):
        assert scrub("plain", ["", None]) == "plain"  # type: ignore[list-item]

    def test_scrub_longest_secret_first(self):
        # A shorter secret that is a prefix of a longer one must not leave the
        # longer one's tail behind.
        out = scrub("token=abcdef123", ["abc", "abcdef123"])
        assert "123" not in out
        assert "abc" not in out

    def test_scrub_process_error_scrubs_cmd_stdout_stderr(self):
        exc = subprocess.CalledProcessError(
            1, ["git", "clone", f"https://x:{INSTALL_TOKEN}@github.com/o/r"]
        )
        exc.stdout = f"out {INSTALL_TOKEN}".encode()
        exc.stderr = f"err {INSTALL_TOKEN}"
        scrub_process_error(exc, [INSTALL_TOKEN])
        assert INSTALL_TOKEN not in str(exc.cmd)
        assert INSTALL_TOKEN not in exc.stdout
        assert INSTALL_TOKEN not in exc.stderr

    def test_scrub_process_error_accepts_secret_set(self):
        # QA/verifier S-180: a SecretSet used to raise TypeError (not iterable).
        exc = subprocess.CalledProcessError(1, ["gh", "api", f"-H=token {PROJECTS_PAT}"])
        exc.stdout = f"out {SUPABASE_KEY}".encode()
        exc.stderr = f"err {APP_PEM}"
        scrub_process_error(exc, _registered())
        assert PROJECTS_PAT not in str(exc.cmd)
        _assert_clean(exc.stdout)
        _assert_clean(exc.stderr)

    def test_scrub_process_error_redacts_unregistered_shapes(self):
        # Known values and known shapes: an Anthropic key, a GitHub token or a
        # PEM block printed by a subprocess is caught even when unregistered.
        for secrets in (SecretSet(), []):
            exc = subprocess.CalledProcessError(
                1, f"curl -H 'x-api-key: {ANTHROPIC_KEY}' -H 'auth: {INSTALL_TOKEN}'"
            )
            exc.stdout = f"key={ANTHROPIC_KEY}\n{APP_PEM}".encode()
            exc.stderr = f"token {PROJECTS_PAT}"
            scrub_process_error(exc, secrets)
            _assert_clean(str(exc.cmd))
            _assert_clean(exc.stdout)
            _assert_clean(exc.stderr)
            assert "sk-ant-" not in exc.stdout


# ---------------------------------------------------------------------------
# Bug-fix extensions: the Anthropic key and the Projects PAT (D-50, D-99)
# ---------------------------------------------------------------------------


class TestAnthropicKey:
    def test_registered_anthropic_key_is_redacted(self):
        secrets = _registered()
        out = scrub_all(f"ANTHROPIC_API_KEY={ANTHROPIC_KEY} done", secrets)
        assert ANTHROPIC_KEY not in out
        assert out.endswith(" done")

    def test_unregistered_anthropic_key_shape_is_redacted(self):
        out = redact_patterns(f"leaked {ANTHROPIC_KEY} here")
        assert ANTHROPIC_KEY not in out
        assert "sk-ant-" not in out


class TestProjectsToken:
    def test_registered_projects_pat_is_redacted(self):
        out = scrub_all(f"Authorization: bearer {PROJECTS_PAT}", _registered())
        assert PROJECTS_PAT not in out

    def test_unregistered_classic_pat_shape_is_redacted(self):
        out = redact_patterns(f"token {PROJECTS_PAT}.")
        assert PROJECTS_PAT not in out
        assert out.endswith(".")

    def test_unregistered_fine_grained_pat_shape_is_redacted(self):
        pat = "github_pat_" + "11ABCDEFG0" * 8
        assert pat not in redact_patterns(f"x {pat} y")

    def test_token_glued_to_a_word_char_is_redacted(self):
        # QA/verifier S-180: a leading word character used to defeat the
        # `\b` anchor, so `xghp_...` and `GH_TOKEN_ghp_...` survived.
        pat = "github_pat_" + "11ABCDEFG0" * 8
        for text in (
            f"x{PROJECTS_PAT}",
            f"GH_TOKEN_{PROJECTS_PAT}",
            f"9{INSTALL_TOKEN}",
            f"x{pat}",
            f"GH_TOKEN_{pat}",
        ):
            out = redact_patterns(text)
            assert PROJECTS_PAT not in out
            assert INSTALL_TOKEN not in out
            assert pat not in out


class TestOtherSecrets:
    def test_installation_token_shape_is_redacted(self):
        assert INSTALL_TOKEN not in redact_patterns(f"x-access-token:{INSTALL_TOKEN}@github.com")

    def test_multiline_pem_is_redacted_unregistered(self):
        out = redact_patterns(f"before\n{APP_PEM}\nafter")
        assert "BEGIN RSA PRIVATE KEY" not in out
        assert "sentinelsentinel" not in out
        assert out.startswith("before\n")
        assert out.endswith("\nafter")

    def test_json_escaped_pem_is_redacted_when_registered(self):
        escaped = json.dumps({"pem": APP_PEM})
        out = scrub_all(escaped, _registered())
        assert "sentinelsentinel" not in out

    def test_supabase_key_registered_is_redacted(self):
        assert SUPABASE_KEY not in scrub_all(f"apikey: {SUPABASE_KEY}", _registered())


class TestSecretSet:
    def test_values_are_listed_and_names_are_not_values(self):
        s = _registered()
        # Every registered value, plus the JSON-escaped form of the PEM.
        assert set(s.values()) == set(ALL) | {json.dumps(APP_PEM)[1:-1]}
        assert "ANTHROPIC_API_KEY" in s.names()

    def test_empty_value_is_ignored(self):
        s = SecretSet()
        s.add("ANTHROPIC_API_KEY", "")
        assert s.values() == []

    def test_repr_never_shows_values(self):
        s = _registered()
        for secret in ALL:
            assert secret not in repr(s)
            assert secret not in str(s)


# ---------------------------------------------------------------------------
# Every surface: exception messages, nested structures, gate tails
# ---------------------------------------------------------------------------


class TestSurfaces:
    def test_exception_message_and_traceback(self):
        secrets = _registered()
        try:
            raise RuntimeError(f"mint failed for {INSTALL_TOKEN} with key {ANTHROPIC_KEY}")
        except RuntimeError as exc:
            out = scrub_exception(exc, secrets)
            assert "RuntimeError" in out
            _assert_clean(out)
            _assert_clean(scrub_all(traceback.format_exc(), secrets))

    def test_nested_dict_list_and_tuple(self):
        payload = {
            "summary": f"key {ANTHROPIC_KEY}",
            "events": [{"msg": f"pat {PROJECTS_PAT}"}, ("tuple", APP_PEM)],
            "count": 3,
            "ok": True,
            "none": None,
        }
        out = scrub_obj(payload, _registered())
        _assert_clean(json.dumps(out))
        assert out["count"] == 3
        assert out["ok"] is True
        assert out["none"] is None
        assert isinstance(out["events"][1], tuple)

    def test_dict_keys_are_scrubbed_too(self):
        out = scrub_obj({ANTHROPIC_KEY: "v"}, _registered())
        _assert_clean(json.dumps(out))

    def test_gate_output_tail_is_scrubbed_and_bounded(self):
        noise = "line\n" * 500
        output = f"{noise}FAILED: auth with {PROJECTS_PAT}\n{APP_PEM}\n"
        out = tail(output, _registered(), max_chars=400)
        assert len(out) <= 400
        _assert_clean(out)

    def test_tail_scrubs_before_cutting(self):
        # A secret straddling the cut point must not leave a fragment behind.
        output = "x" * 50 + ANTHROPIC_KEY + "y" * 10
        cut = len("y" * 10) + 20
        out = tail(output, _registered(), max_chars=cut)
        assert ANTHROPIC_KEY[-15:] not in out

    def test_bytes_tail_is_decoded(self):
        out = tail(f"err {INSTALL_TOKEN}".encode(), _registered(), max_chars=100)
        assert INSTALL_TOKEN not in out


# ---------------------------------------------------------------------------
# Property tests (RT tactics; hypothesis per test plan G-5)
# ---------------------------------------------------------------------------

_TEXT = st.text(alphabet=st.characters(codec="utf-8"), max_size=200)


@given(prefix=_TEXT, suffix=_TEXT)
def test_registered_secrets_never_survive(prefix: str, suffix: str) -> None:
    secrets = _registered()
    for secret in ALL:
        assert secret not in scrub_all(prefix + secret + suffix, secrets)


@given(
    body=st.text(
        alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-",
        min_size=20,
        max_size=120,
    )
)
def test_any_anthropic_key_shape_is_redacted(body: str) -> None:
    key = "sk-ant-" + body
    assert key not in redact_patterns(f"k={key};")


@given(
    body=st.text(
        alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
        min_size=36,
        max_size=36,
    ),
    prefix=st.sampled_from(["ghp_", "ghs_", "gho_", "ghu_", "ghr_"]),
)
def test_any_github_token_shape_is_redacted(body: str, prefix: str) -> None:
    token = prefix + body
    assert token not in redact_patterns(f"t {token} t")


_WORD = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_"


@given(
    lead=st.text(alphabet=_WORD, max_size=20),
    body=st.text(alphabet=_WORD[:-1], min_size=36, max_size=60),
    prefix=st.sampled_from(["ghp_", "ghs_", "gho_", "ghu_", "ghr_"]),
)
def test_github_token_with_word_char_prefix_is_redacted(lead: str, body: str, prefix: str) -> None:
    token = prefix + body
    assert token not in redact_patterns(lead + token)


@given(
    lead=st.text(alphabet=_WORD, max_size=20),
    body=st.text(alphabet=_WORD, min_size=20, max_size=90),
)
def test_fine_grained_pat_with_word_char_prefix_is_redacted(lead: str, body: str) -> None:
    pat = "github_pat_" + body
    assert pat not in redact_patterns(lead + pat)


@given(text=_TEXT)
def test_scrub_all_is_idempotent(text: str) -> None:
    secrets = _registered()
    once = scrub_all(text, secrets)
    assert scrub_all(once, secrets) == once
