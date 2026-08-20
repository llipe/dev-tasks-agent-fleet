"""Structured JSON logging helper for the dep-updater agent.

Emits one JSON object per line to stdout, binding session_id, agent, and repo
once at initialization. All output is redacted for secrets before emission.

Usage:
    from logging_json import JsonLogger
    log = JsonLogger(session_id="...", agent="dep-updater", repo="owner/repo")
    log.info("lifecycle event")
    log.warn("non-fatal issue", detail="...")
    log.error("failure", error="...")
    log.subprocess_output("line from cmd", stream_name="stdout")
"""

import json
import re
import sys
from datetime import UTC, datetime
from typing import IO, Any

# ─────────────────────────────────────────────────────────────────
# Secret redaction
# ─────────────────────────────────────────────────────────────────

# Patterns that match token-shaped values:
# - GitHub PATs: ghp_..., ghs_..., github_pat_...
# - AWS Access Key IDs: AKIA...
# - AWS Secret Keys / generic long base64: mixed-case alphanum with special chars
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    # GitHub PATs (classic): ghp_ or ghs_ followed by 20+ alphanumeric chars
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"ghs_[A-Za-z0-9]{20,}"),
    # GitHub fine-grained PAT: github_pat_ followed by alphanum/underscores
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    # AWS Access Key ID: starts with AKIA followed by 16 uppercase alphanum
    re.compile(r"AKIA[A-Z0-9]{16}"),
    # AWS Secret Access Key / generic secret: 40+ chars of mixed-case alphanum
    # with /, +, = (base64-like). Must contain at least one uppercase, one
    # lowercase, and one digit or special to avoid matching plain repeated chars.
    re.compile(r"(?<![A-Za-z0-9/+=])(?=[A-Za-z0-9/+=]*[A-Z])(?=[A-Za-z0-9/+=]*[a-z])[A-Za-z0-9/+=]{40,}(?![A-Za-z0-9/+=])"),
]

_REDACTED = "***REDACTED***"


def redact_secrets(text: str) -> str:
    """Replace token-shaped values in text with ***REDACTED***.

    Applies multiple patterns to catch GitHub PATs, AWS keys, and generic
    long base64-like tokens.
    """
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return text


# ─────────────────────────────────────────────────────────────────
# JSON Logger
# ─────────────────────────────────────────────────────────────────


class JsonLogger:
    """Structured JSON logger that binds context fields once.

    Each call to info/warn/error emits a single JSON line to the stream.
    All messages are automatically redacted for secrets.
    """

    def __init__(
        self,
        session_id: str,
        agent: str,
        repo: str,
        stream: IO[str] | None = None,
    ) -> None:
        self._context = {
            "session_id": session_id,
            "agent": agent,
            "repo": repo,
        }
        self._stream: IO[str] = stream if stream is not None else sys.stdout

    def _emit(self, level: str, msg: str, **extra: Any) -> None:
        """Emit a single JSON log line."""
        # Redact secrets from the message and all string extra values
        msg = redact_secrets(msg)
        for key, value in extra.items():
            if isinstance(value, str):
                extra[key] = redact_secrets(value)

        record: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": level,
            "msg": msg,
            **self._context,
            **extra,
        }
        # ensure_ascii=False for proper unicode, but newlines in msg are escaped
        # by json.dumps automatically
        line = json.dumps(record, ensure_ascii=False, default=str)
        self._stream.write(line + "\n")
        self._stream.flush()

    def info(self, msg: str, **extra: Any) -> None:
        """Log an info-level message (lifecycle events)."""
        self._emit("info", msg, **extra)

    def warn(self, msg: str, **extra: Any) -> None:
        """Log a warn-level message (retries, non-fatal issues)."""
        self._emit("warn", msg, **extra)

    def error(self, msg: str, **extra: Any) -> None:
        """Log an error-level message (failures)."""
        self._emit("error", msg, **extra)

    def subprocess_output(self, msg: str, stream_name: str, **extra: Any) -> None:
        """Log a subprocess output line with stream field.

        Each line of subprocess stdout/stderr is logged as a separate JSON
        entry with a `stream` field for CloudWatch searchability.
        """
        self._emit("info", msg, stream=stream_name, **extra)

    def log_subprocess_lines(
        self, output: str, stream_name: str, prefix: str = ""
    ) -> None:
        """Log multi-line subprocess output as individual JSON lines.

        Args:
            output: Multi-line string from subprocess stdout or stderr.
            stream_name: "stdout" or "stderr".
            prefix: Optional prefix for the command context.
        """
        if not output:
            return
        extra: dict[str, Any] = {}
        if prefix:
            extra["cmd"] = prefix
        for line in output.splitlines():
            if line.strip():  # Skip empty lines
                self.subprocess_output(line, stream_name=stream_name, **extra)
