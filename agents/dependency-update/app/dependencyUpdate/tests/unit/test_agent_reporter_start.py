"""Unit tests for the zero-match ``start()`` guard (issue #100, AC3).

Per D1 the control plane INSERTs the ``queued`` runs row before invoking; the
agent SDK only PATCHes it. If nobody inserted the row, PostgREST answers the
zero-match UPDATE with HTTP 200 and the run vanishes with no error. AC3 makes
``RunReporter.start()`` detect the zero-row PATCH and warn loudly (to stderr →
CloudWatch) **without aborting** — reporting must never kill the agent.

Coverage:
- ``_parse_content_range_count`` header parsing (0-0/1, */0, missing, junk).
- ``_SupabaseClient.update_expect_rows`` returns the affected-row count parsed
  from ``Content-Range`` (mocked ``urllib``), and ``None`` on failure.
- ``RunReporter.start()`` warns on a confirmed zero, stays silent otherwise,
  and never raises regardless of the count outcome.
"""

from __future__ import annotations

import io
import urllib.error
from unittest import mock

import pytest

import agent_reporter
from agent_reporter import RunReporter, _parse_content_range_count, _SupabaseClient

# --------------------------------------------------------------- header parsing


@pytest.mark.parametrize(
    "header,expected",
    [
        ("0-0/1", 1),
        ("0-4/5", 5),
        ("*/0", 0),
        ("*/12", 12),
        (None, None),
        ("", None),
        ("garbage", None),
        ("0-0/*", None),  # unknown total → not a digit
        ("0-0/", None),
    ],
)
def test_parse_content_range_count(header, expected):
    assert _parse_content_range_count(header) == expected


# --------------------------------------------------------- update_expect_rows


class _FakeResp:
    def __init__(self, status: int, content_range: str | None):
        self.status = status
        self.headers = {"Content-Range": content_range} if content_range is not None else {}

    def read(self):
        return b""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _client() -> _SupabaseClient:
    return _SupabaseClient("https://example.supabase.co", "svc-key")


def test_update_expect_rows_returns_one_on_match():
    resp = _FakeResp(200, "0-0/1")
    with mock.patch.object(agent_reporter.urllib.request, "urlopen", return_value=resp):
        n = _client().update_expect_rows("runs", "id=eq.abc", {"status": "running"})
    assert n == 1


def test_update_expect_rows_returns_zero_on_no_match():
    resp = _FakeResp(200, "*/0")
    with mock.patch.object(agent_reporter.urllib.request, "urlopen", return_value=resp):
        n = _client().update_expect_rows("runs", "id=eq.missing", {"status": "running"})
    assert n == 0


def test_update_expect_rows_sends_count_exact_prefer_header():
    resp = _FakeResp(200, "0-0/1")
    captured = {}

    def _fake_urlopen(req, timeout=None):
        # urllib normalizes header keys to Capitalized form
        captured["prefer"] = req.get_header("Prefer")
        captured["method"] = req.get_method()
        return resp

    with mock.patch.object(agent_reporter.urllib.request, "urlopen", side_effect=_fake_urlopen):
        _client().update_expect_rows("runs", "id=eq.abc", {"status": "running"})
    assert captured["method"] == "PATCH"
    assert "count=exact" in captured["prefer"]


def test_update_expect_rows_returns_none_on_4xx_without_retry():
    err = urllib.error.HTTPError("u", 400, "Bad Request", {}, io.BytesIO(b"bad"))
    with mock.patch.object(agent_reporter.urllib.request, "urlopen", side_effect=err) as m:
        n = _client().update_expect_rows("runs", "id=eq.abc", {"status": "running"})
    assert n is None
    assert m.call_count == 1  # 4xx (non-429) is a contract error: no retry


def test_update_expect_rows_never_raises_on_transient_error():
    with (
        mock.patch.object(
            agent_reporter.urllib.request, "urlopen", side_effect=OSError("network down")
        ),
        mock.patch.object(agent_reporter.time, "sleep"),
    ):
        n = _client().update_expect_rows("runs", "id=eq.abc", {"status": "running"})
    assert n is None  # exhausted retries → None, no exception


# ------------------------------------------------------------------- start()


def _reporter() -> RunReporter:
    # capture_logging=False keeps the test free of the logging handler side effects
    return RunReporter(
        "https://example.supabase.co",
        "svc-key",
        run_id="11111111-1111-1111-1111-111111111111",
        capture_logging=False,
    )


def test_start_warns_on_zero_rows(capsys):
    r = _reporter()
    with (
        mock.patch.object(r._db, "update_expect_rows", return_value=0),
        mock.patch.object(r, "log"),
    ):
        r.start()  # must not raise
    err = capsys.readouterr().err
    assert "0 filas afectadas" in err
    assert "#100" in err
    assert r.run_id in err


def test_start_silent_on_match(capsys):
    r = _reporter()
    with (
        mock.patch.object(r._db, "update_expect_rows", return_value=1),
        mock.patch.object(r, "log"),
    ):
        r.start()
    err = capsys.readouterr().err
    assert "ADVERTENCIA" not in err


def test_start_silent_when_count_unknown(capsys):
    # A None count (request failed / header missing) must NOT emit the #100
    # warning — we only warn on a *confirmed* zero to avoid false alarms.
    r = _reporter()
    with (
        mock.patch.object(r._db, "update_expect_rows", return_value=None),
        mock.patch.object(r, "log"),
    ):
        r.start()
    err = capsys.readouterr().err
    assert "#100" not in err


def test_start_never_raises_even_on_zero():
    r = _reporter()
    with (
        mock.patch.object(r._db, "update_expect_rows", return_value=0),
        mock.patch.object(r, "log"),
    ):
        # explicit: reporting a missing row must not propagate an exception
        r.start()
