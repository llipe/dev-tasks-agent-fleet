"""
The run link: one strict validator for the panel link in every agent comment
(S-190; S-188 QA gap 2; spec §8.3; D-53, D-104).

Each comment the agent posts (the claim, the refusal reply, the diagnosis)
ends with a link to the run in the panel, ``<panel origin>/runs/<run_id>``.
The panel origin is the ``PANEL_BASE_URL`` runtime variable. This module is
the only place that checks either one:

- :func:`parse_origin` validates ``PANEL_BASE_URL`` for ``config.load_config``:
  a bare ``https`` origin (a DNS host and an optional port), with no userinfo,
  path, query or fragment, and no whitespace or control character.
- :class:`RunLink` is a ``str`` that only a validated origin and a run id can
  build. ``Config.run_link`` is its one production source, so a run link's
  host is always the configured panel host.
- :func:`is_valid_run_link` is what every comment builder calls. It accepts a
  :class:`RunLink` only, never a plain string, and re-checks it in full: the
  ``https`` scheme, no userinfo, the host equal to the link's own origin (and
  to ``origin`` when the caller passes the configured one), the path
  ``/runs/<this comment's run id>``, no query or fragment, printable ASCII
  only (so no whitespace, control character, or zero-width space), and no
  ``javascript:`` scheme.
- :func:`run_ref` returns the link, or the run id in backticks when the link
  is unusable. A missing or bad link therefore never fails a run, and nothing
  but this grammar can reach a comment's last line.

Errors name the reason only, never the value.
"""

from __future__ import annotations

import re
import uuid
from urllib.parse import urlsplit

__all__ = ["RunLink", "is_valid_run_link", "make_run_link", "parse_origin", "run_ref"]

# One DNS label: letters, digits and inner hyphens.
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_HOST = re.compile(rf"{_LABEL}(?:\.{_LABEL})*")
_PORT = re.compile(r"[0-9]{1,5}")
_MAX_HOST = 253


def _printable_ascii(text: str) -> bool:
    """No whitespace, control, non-ASCII or zero-width character."""
    return all(0x21 <= ord(c) <= 0x7E for c in text)


def _split_netloc(netloc: str) -> tuple[str, int | None] | None:
    """``(host, port)`` for a ``host[:port]`` netloc, or ``None`` if it isn't one."""
    if "@" in netloc:
        return None
    host, sep, port = netloc.partition(":")
    if len(host) > _MAX_HOST or not _HOST.fullmatch(host):
        return None
    if not sep:
        return host, None
    if not _PORT.fullmatch(port) or not 1 <= int(port) <= 65535:
        return None
    return host, int(port)


def parse_origin(raw: object) -> str:
    """The panel origin, without a trailing slash. Raises ``ValueError``."""
    if not isinstance(raw, str):
        raise ValueError("must be a string")
    value = raw.strip().removesuffix("/")
    if not value or not _printable_ascii(value):
        raise ValueError("must be an https origin with no whitespace or control characters")
    if value.lower().startswith("javascript:"):
        raise ValueError("must be an https origin")
    scheme, sep, netloc = value.partition("://")
    if not sep or scheme != "https":
        raise ValueError("must be an https origin")
    if any(c in netloc for c in "/?#"):
        raise ValueError("must be an https origin with no path, query or fragment")
    if _split_netloc(netloc) is None:
        raise ValueError("must be an https origin: a DNS host, an optional port, no userinfo")
    return value


def _canonical(run_id: object) -> str:
    if not isinstance(run_id, str):
        raise ValueError("run id must be a UUID")
    try:
        return str(uuid.UUID(run_id))
    except ValueError:
        raise ValueError("run id must be a UUID") from None


class RunLink(str):
    """``<origin>/runs/<run_id>``, built only from a validated origin.

    ``origin`` is the configured panel origin and ``run_id`` the canonical run
    id. Comment builders accept nothing else as a link (QA gap 2).
    """

    origin: str
    run_id: str

    def __new__(cls, origin: str, run_id: str) -> RunLink:
        base = parse_origin(origin)
        rid = _canonical(run_id)
        link = super().__new__(cls, f"{base}/runs/{rid}")
        link.origin = base
        link.run_id = rid
        return link


def make_run_link(origin: str | None, run_id: object) -> RunLink | None:
    """A :class:`RunLink`, or ``None`` without an origin or with a non-UUID run id."""
    if origin is None:
        return None
    try:
        return RunLink(origin, run_id)  # type: ignore[arg-type]
    except ValueError:
        return None


def _host_port(origin: str) -> tuple[str, int | None] | None:
    try:
        base = parse_origin(origin)
    except ValueError:
        return None
    hp = _split_netloc(base.partition("://")[2])
    if hp is None:  # pragma: no cover - parse_origin already checked it
        return None
    return hp[0].lower(), hp[1]


def is_valid_run_link(link: object, run_id: object, origin: str | None = None) -> bool:
    """True iff ``link`` is a usable panel link for ``run_id`` (module docstring)."""
    if not isinstance(link, RunLink):
        return False
    text = str.__str__(link)
    if not text or not _printable_ascii(text) or text.lower().startswith("javascript:"):
        return False
    try:
        rid = _canonical(run_id)
    except ValueError:
        return False
    parts = urlsplit(text)
    if parts.scheme != "https" or parts.query or parts.fragment or "?" in text or "#" in text:
        return False
    hp = _split_netloc(parts.netloc)
    if hp is None or parts.path != f"/runs/{rid}":
        return False
    if text != f"https://{parts.netloc}/runs/{rid}":
        return False
    host = (hp[0].lower(), hp[1])
    own = _host_port(getattr(link, "origin", ""))
    if own is None or own != host:
        return False
    return origin is None or _host_port(origin) == host


def run_ref(link: object, run_id: str, origin: str | None = None) -> str:
    """The link when :func:`is_valid_run_link`, else the run id in backticks."""
    if is_valid_run_link(link, run_id, origin):
        return str.__str__(link)  # type: ignore[arg-type]
    try:
        return f"`{_canonical(run_id)}`"
    except ValueError:
        return "`unknown run`"
