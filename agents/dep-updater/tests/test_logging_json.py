"""Tests for structured JSON logging (S-008).

Covers:
- 8.6: Emitted line parses as JSON with required fields
- 8.7: Redaction helper strips token-shaped values
- 8.8: Messages with quotes/newlines/non-UTF8 do not break JSON
"""

import io
import json


class TestJsonLogOutput:
    """8.6: Emitted line parses as JSON with required fields."""

    def test_single_log_line_is_valid_json(self) -> None:
        """Each log call produces exactly one JSON object on one line."""
        from logging_json import JsonLogger

        buf = io.StringIO()
        logger = JsonLogger(
            session_id="sess-001",
            agent="dep-updater",
            repo="owner/repo",
            stream=buf,
        )
        logger.info("hello world")
        output = buf.getvalue()
        lines = output.strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert isinstance(parsed, dict)

    def test_required_fields_present(self) -> None:
        """Every log line must include ts, level, msg, session_id, agent, repo."""
        from logging_json import JsonLogger

        buf = io.StringIO()
        logger = JsonLogger(
            session_id="sess-abc",
            agent="dep-updater",
            repo="owner/my-repo",
            stream=buf,
        )
        logger.info("lifecycle event")
        parsed = json.loads(buf.getvalue().strip())
        assert parsed["session_id"] == "sess-abc"
        assert parsed["agent"] == "dep-updater"
        assert parsed["repo"] == "owner/my-repo"
        assert parsed["level"] == "info"
        assert parsed["msg"] == "lifecycle event"
        assert "ts" in parsed

    def test_log_levels(self) -> None:
        """info, warn, error levels are correctly emitted."""
        from logging_json import JsonLogger

        buf = io.StringIO()
        logger = JsonLogger(
            session_id="s1", agent="dep-updater", repo="o/r", stream=buf
        )
        logger.info("info msg")
        logger.warn("warn msg")
        logger.error("error msg")
        lines = buf.getvalue().strip().split("\n")
        assert len(lines) == 3
        assert json.loads(lines[0])["level"] == "info"
        assert json.loads(lines[1])["level"] == "warn"
        assert json.loads(lines[2])["level"] == "error"

    def test_extra_fields_included(self) -> None:
        """Additional fields passed as kwargs appear in JSON output."""
        from logging_json import JsonLogger

        buf = io.StringIO()
        logger = JsonLogger(
            session_id="s1", agent="dep-updater", repo="o/r", stream=buf
        )
        logger.info("with extra", exit_code=1, stream="stdout")
        parsed = json.loads(buf.getvalue().strip())
        assert parsed["exit_code"] == 1
        assert parsed["stream"] == "stdout"

    def test_subprocess_output_line_has_stream_field(self) -> None:
        """Subprocess output logged per-line includes stream field."""
        from logging_json import JsonLogger

        buf = io.StringIO()
        logger = JsonLogger(
            session_id="s1", agent="dep-updater", repo="o/r", stream=buf
        )
        logger.subprocess_output("some output line", stream_name="stdout")
        parsed = json.loads(buf.getvalue().strip())
        assert parsed["stream"] == "stdout"
        assert parsed["msg"] == "some output line"
        assert parsed["level"] == "info"

    def test_timestamp_is_iso_format(self) -> None:
        """Timestamp should be in ISO 8601 format."""
        from logging_json import JsonLogger

        buf = io.StringIO()
        logger = JsonLogger(
            session_id="s1", agent="dep-updater", repo="o/r", stream=buf
        )
        logger.info("check ts")
        parsed = json.loads(buf.getvalue().strip())
        ts = parsed["ts"]
        # Should contain date and time separator
        assert "T" in ts or "-" in ts


class TestSecretRedaction:
    """8.7: Redaction helper strips token-shaped values."""

    def test_redacts_github_pat_ghp(self) -> None:
        """GitHub PAT starting with ghp_ should be redacted."""
        from logging_json import redact_secrets

        text = "token is ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ123456"
        result = redact_secrets(text)
        assert "ghp_" not in result
        assert "***REDACTED***" in result

    def test_redacts_github_pat_ghs(self) -> None:
        """GitHub server token starting with ghs_ should be redacted."""
        from logging_json import redact_secrets

        text = "using ghs_AbCdEfGhIjKlMnOpQrStUvWxYz1234"
        result = redact_secrets(text)
        assert "ghs_" not in result
        assert "***REDACTED***" in result

    def test_redacts_github_pat_long_format(self) -> None:
        """GitHub fine-grained PAT starting with github_pat_ should be redacted."""
        from logging_json import redact_secrets

        text = "cred=github_pat_11ABCDEFG0aBcDeFgHiJkL_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        result = redact_secrets(text)
        assert "github_pat_" not in result
        assert "***REDACTED***" in result

    def test_redacts_aws_access_key(self) -> None:
        """AWS access key ID (AKIA...) should be redacted."""
        from logging_json import redact_secrets

        text = "key=AKIAIOSFODNN7EXAMPLE"
        result = redact_secrets(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "***REDACTED***" in result

    def test_redacts_aws_secret_key(self) -> None:
        """AWS secret access key (40 char base64-like) should be redacted."""
        from logging_json import redact_secrets

        text = "secret=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        result = redact_secrets(text)
        assert "wJalrXUtnFEMI" not in result
        assert "***REDACTED***" in result

    def test_redacts_generic_long_base64_token(self) -> None:
        """Long base64-like strings (40+ chars, mixed case) should be redacted."""
        from logging_json import redact_secrets

        # 50 char mixed-case base64-like string
        token = "wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEYsecretABCD"
        text = f"auth={token}"
        result = redact_secrets(text)
        assert token not in result
        assert "***REDACTED***" in result

    def test_preserves_normal_text(self) -> None:
        """Normal text without token patterns should not be altered."""
        from logging_json import redact_secrets

        text = "cloning https://github.com/owner/repo into /tmp/workspace"
        result = redact_secrets(text)
        assert result == text

    def test_preserves_short_strings(self) -> None:
        """Short alphanumeric strings should not be redacted."""
        from logging_json import redact_secrets

        text = "pnpm version 9.15.4 installed"
        result = redact_secrets(text)
        assert result == text

    def test_multiple_tokens_all_redacted(self) -> None:
        """Multiple tokens in the same string should all be redacted."""
        from logging_json import redact_secrets

        text = "token=ghp_abcdefghijklmnopqrstuvwxyz123456 key=AKIAIOSFODNN7EXAMPLE"
        result = redact_secrets(text)
        assert "ghp_" not in result
        assert "AKIA" not in result
        assert result.count("***REDACTED***") == 2

    def test_redaction_applied_in_log_output(self) -> None:
        """Secrets in log messages are automatically redacted."""
        from logging_json import JsonLogger

        buf = io.StringIO()
        logger = JsonLogger(
            session_id="s1", agent="dep-updater", repo="o/r", stream=buf
        )
        logger.info("token is ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ123456")
        parsed = json.loads(buf.getvalue().strip())
        assert "ghp_" not in parsed["msg"]
        assert "***REDACTED***" in parsed["msg"]


class TestSpecialCharacters:
    """8.8: Messages with quotes/newlines/non-UTF8 do not break JSON."""

    def test_message_with_double_quotes(self) -> None:
        """Double quotes in message must not break JSON."""
        from logging_json import JsonLogger

        buf = io.StringIO()
        logger = JsonLogger(
            session_id="s1", agent="dep-updater", repo="o/r", stream=buf
        )
        logger.info('file "package.json" not found')
        output = buf.getvalue().strip()
        parsed = json.loads(output)
        assert parsed["msg"] == 'file "package.json" not found'

    def test_message_with_newlines(self) -> None:
        """Newlines in message must be escaped; output is still one line."""
        from logging_json import JsonLogger

        buf = io.StringIO()
        logger = JsonLogger(
            session_id="s1", agent="dep-updater", repo="o/r", stream=buf
        )
        logger.info("line1\nline2\nline3")
        output = buf.getvalue()
        # Must be a single line (JSON with escaped newlines)
        lines = output.strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["msg"] == "line1\nline2\nline3"

    def test_message_with_backslashes(self) -> None:
        """Backslashes must be properly escaped."""
        from logging_json import JsonLogger

        buf = io.StringIO()
        logger = JsonLogger(
            session_id="s1", agent="dep-updater", repo="o/r", stream=buf
        )
        logger.info("path is C:\\Users\\test\\file.txt")
        parsed = json.loads(buf.getvalue().strip())
        assert parsed["msg"] == "path is C:\\Users\\test\\file.txt"

    def test_message_with_unicode(self) -> None:
        """Unicode characters must not break JSON."""
        from logging_json import JsonLogger

        buf = io.StringIO()
        logger = JsonLogger(
            session_id="s1", agent="dep-updater", repo="o/r", stream=buf
        )
        logger.info("emoji: \U0001f680 and accents: caf\u00e9")
        parsed = json.loads(buf.getvalue().strip())
        assert "\U0001f680" in parsed["msg"]
        assert "caf\u00e9" in parsed["msg"]

    def test_message_with_null_bytes(self) -> None:
        """Null bytes should be handled without breaking JSON."""
        from logging_json import JsonLogger

        buf = io.StringIO()
        logger = JsonLogger(
            session_id="s1", agent="dep-updater", repo="o/r", stream=buf
        )
        logger.info("data\x00with\x00nulls")
        output = buf.getvalue().strip()
        # Must still be valid JSON
        parsed = json.loads(output)
        assert "data" in parsed["msg"]

    def test_message_with_control_characters(self) -> None:
        """Control characters must be properly escaped."""
        from logging_json import JsonLogger

        buf = io.StringIO()
        logger = JsonLogger(
            session_id="s1", agent="dep-updater", repo="o/r", stream=buf
        )
        logger.info("tab\there\rand\x1b[31mcolor")
        output = buf.getvalue().strip()
        parsed = json.loads(output)
        assert "tab" in parsed["msg"]

    def test_very_long_message(self) -> None:
        """Very long messages should still produce valid JSON."""
        from logging_json import JsonLogger

        buf = io.StringIO()
        logger = JsonLogger(
            session_id="s1", agent="dep-updater", repo="o/r", stream=buf
        )
        long_msg = "x" * 10000
        logger.info(long_msg)
        parsed = json.loads(buf.getvalue().strip())
        assert len(parsed["msg"]) == 10000
