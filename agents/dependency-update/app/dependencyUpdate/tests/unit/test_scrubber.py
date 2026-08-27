"""Unit tests for scrubber module."""

from __future__ import annotations

import subprocess

import pytest

from scrubber import scrub, scrub_process_error


class TestScrub:
    def test_removes_single_token(self):
        text = "Authorization: Bearer ghp_abc123secret"
        result = scrub(text, ["ghp_abc123secret"])
        assert "ghp_abc123secret" not in result
        assert "Authorization: Bearer ***" == result

    def test_removes_token_appearing_multiple_times(self):
        text = "token=ghp_x; again ghp_x end"
        result = scrub(text, ["ghp_x"])
        assert result == "token=***; again *** end"

    def test_removes_multiple_different_secrets(self):
        text = "key=SECRET1 and token=SECRET2"
        result = scrub(text, ["SECRET1", "SECRET2"])
        assert "SECRET1" not in result
        assert "SECRET2" not in result
        assert result == "key=*** and token=***"

    def test_empty_secret_is_skipped(self):
        text = "nothing to scrub"
        result = scrub(text, ["", None])  # type: ignore[list-item]
        assert result == text

    def test_no_secrets_returns_unchanged(self):
        text = "safe text"
        result = scrub(text, [])
        assert result == text

    def test_secret_at_boundaries(self):
        text = "TOKENstartTOKEN"
        result = scrub(text, ["TOKEN"])
        assert result == "***start***"

    def test_overlapping_secrets_handled(self):
        # Longer secret should be scrubbed first if listed first
        text = "ghp_abcdef123"
        result = scrub(text, ["ghp_abcdef123", "ghp_abc"])
        assert "ghp" not in result


class TestScrubProcessError:
    def _make_error(self, cmd, stdout=None, stderr=None):
        exc = subprocess.CalledProcessError(1, cmd)
        exc.stdout = stdout
        exc.stderr = stderr
        return exc

    def test_scrubs_cmd_as_list(self):
        exc = self._make_error(["git", "clone", "https://x-access-token:SECRET@github.com/org/repo"])
        scrub_process_error(exc, ["SECRET"])
        assert "SECRET" not in exc.cmd
        assert "***" in exc.cmd

    def test_scrubs_cmd_as_string(self):
        exc = self._make_error("curl -H 'Authorization: Bearer TOKEN123'")
        scrub_process_error(exc, ["TOKEN123"])
        assert "TOKEN123" not in exc.cmd

    def test_scrubs_stderr(self):
        exc = self._make_error("cmd", stderr="error: token ghp_leak was rejected")
        scrub_process_error(exc, ["ghp_leak"])
        assert "ghp_leak" not in exc.stderr
        assert "***" in exc.stderr

    def test_scrubs_stdout(self):
        exc = self._make_error("cmd", stdout="output contains SECRET_VAL here")
        scrub_process_error(exc, ["SECRET_VAL"])
        assert "SECRET_VAL" not in exc.stdout

    def test_handles_none_stdout_stderr(self):
        exc = self._make_error("cmd", stdout=None, stderr=None)
        # Should not raise
        scrub_process_error(exc, ["anything"])
        assert exc.stdout is None
        assert exc.stderr is None

    def test_handles_bytes_stderr(self):
        exc = self._make_error("cmd", stderr=b"bytes with SECRET inside")
        scrub_process_error(exc, ["SECRET"])
        assert "SECRET" not in exc.stderr
        assert isinstance(exc.stderr, str)
