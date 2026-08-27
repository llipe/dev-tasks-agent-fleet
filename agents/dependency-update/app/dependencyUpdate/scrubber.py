"""
Token scrubbing — removes secrets from text output and subprocess errors.
"""

from __future__ import annotations

import subprocess


def scrub(text: str, secrets: list[str]) -> str:
    """Replace any occurrence of known secrets with '***'."""
    for s in secrets:
        if s and s in text:
            text = text.replace(s, "***")
    return text


def scrub_process_error(
    exc: subprocess.CalledProcessError, secrets: list[str]
) -> None:
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
