# Copied from agents/security-analyst/app/securityAnalyst/scrubber.py
# Source commit: 8cfed33b9974f82047b065732ad956936d3fb5d0
# Extended (S-180): `scrub` replaces the longest secret first; added SecretSet,
# shape-based redaction (Anthropic key, GitHub tokens, PEM blocks), scrub_all,
# scrub_obj, scrub_exception and tail (spec §12 item 6, D-50, D-99, FR-34).
"""
Token scrubbing — removes secrets from text output and subprocess errors.

Two layers:

1. **Known values.** Every secret the wrapper resolves (the Supabase key, the
   App PEM, the installation token, the Anthropic API key and the Projects
   token) is registered in a :class:`SecretSet` and replaced verbatim.
2. **Known shapes.** Anything shaped like an Anthropic key, a GitHub token or a
   PEM private-key block is redacted even if it was never registered, so a
   value the wrapper never saw (for example, one printed by a repo script) is
   still caught.

Everything bound for ``run_events``, ``runs.result``, a PR body or an issue
comment goes through :func:`scrub_all`, :func:`scrub_obj` or :func:`tail`.
"""

from __future__ import annotations

import json
import re
import subprocess
import traceback
from typing import Any

REDACTED = "***"

# Shapes redacted even when the value was never registered.
_PATTERNS: tuple[re.Pattern[str], ...] = (
    # PEM private key blocks (multi-line), including a truncated block whose
    # END line was cut off by a tail.
    re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
        re.DOTALL,
    ),
    # Anthropic API keys: sk-ant-api03-..., sk-ant-admin01-..., etc.
    re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"),
    # GitHub fine-grained PATs.
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    # GitHub classic PATs and App/OAuth tokens: ghp_, gho_, ghu_, ghs_, ghr_.
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}"),
)


class SecretSet:
    """Named secret values held in wrapper memory.

    ``repr``/``str`` list names only, never values, so the set can be logged.
    Multi-line values (the App PEM) also register their JSON-escaped form, so a
    secret that was serialized into JSON is still caught.
    """

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def add(self, name: str, value: str | None) -> None:
        """Register ``value`` under ``name``. Empty values are ignored."""
        if value:
            self._values[name] = value

    def names(self) -> list[str]:
        return sorted(self._values)

    def values(self) -> list[str]:
        out: list[str] = []
        for value in self._values.values():
            out.append(value)
            escaped = json.dumps(value)[1:-1]
            if escaped != value:
                out.append(escaped)
        return out

    def __repr__(self) -> str:
        return f"SecretSet(names={self.names()!r})"

    __str__ = __repr__


SecretsLike = SecretSet | list[str]


def _as_list(secrets: SecretsLike) -> list[str]:
    return secrets.values() if isinstance(secrets, SecretSet) else list(secrets)


def scrub(text: str, secrets: list[str]) -> str:
    """Replace any occurrence of known secrets with '***' (longest first)."""
    for s in sorted((s for s in secrets if s), key=len, reverse=True):
        if s in text:
            text = text.replace(s, REDACTED)
    return text


def redact_patterns(text: str) -> str:
    """Redact anything shaped like a known credential, registered or not."""
    for pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def scrub_all(text: str, secrets: SecretsLike) -> str:
    """Known values first, then known shapes."""
    return redact_patterns(scrub(text, _as_list(secrets)))


def scrub_obj(obj: Any, secrets: SecretsLike) -> Any:
    """Recursively scrub strings in dicts (keys and values), lists and tuples."""
    values = _as_list(secrets)

    def _walk(node: Any) -> Any:
        if isinstance(node, str):
            return redact_patterns(scrub(node, values))
        if isinstance(node, dict):
            return {_walk(k): _walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_walk(v) for v in node]
        if isinstance(node, tuple):
            return tuple(_walk(v) for v in node)
        return node

    return _walk(obj)


def scrub_exception(exc: BaseException, secrets: SecretsLike) -> str:
    """``Type: message`` of ``exc``, scrubbed."""
    return scrub_all("".join(traceback.format_exception_only(exc)).strip(), secrets)


def tail(output: str | bytes, secrets: SecretsLike, max_chars: int = 4000) -> str:
    """Scrub the whole output, then keep its last ``max_chars`` characters.

    Scrubbing before cutting means a secret straddling the cut point can't
    leave a recognisable fragment behind.
    """
    text = output.decode("utf-8", "replace") if isinstance(output, bytes) else output
    clean = scrub_all(text, secrets)
    return clean[-max_chars:] if max_chars > 0 else ""


def scrub_process_error(exc: subprocess.CalledProcessError, secrets: list[str]) -> None:
    """Scrub cmd, stdout, and stderr of a CalledProcessError in-place."""
    cmd_str = " ".join(exc.cmd) if isinstance(exc.cmd, list) else str(exc.cmd)
    exc.cmd = scrub(cmd_str, secrets)
    if exc.stderr:
        exc.stderr = scrub(
            exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode("utf-8", "replace"),
            secrets,
        )
    if exc.stdout:
        exc.stdout = scrub(
            exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode("utf-8", "replace"),
            secrets,
        )
