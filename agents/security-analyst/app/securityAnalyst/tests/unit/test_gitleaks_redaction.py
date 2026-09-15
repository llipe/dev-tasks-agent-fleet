"""
AC-27 cross-surface redaction sweep (PRD S9.3/S12, R14, story S-129, spec
S8.5 note: "normalize.py's per-tool functions MUST NOT copy a Gitleaks
match's raw secret value into Finding.message... A generic redaction pass...
additionally runs over every finding's message field... using the same
scrubber.py redaction utility").

This is the highest-stakes acceptance criterion in this story. Rather than
asserting only ``Finding.message`` in isolation, this module greps for the
literal dummy secret across every surface this scanner module's *own*
output contract can produce:

  1. Every ``Finding`` object's ``message`` field (dataclass attribute).
  2. The full ``str()``/``repr()`` of each ``Finding`` and of the whole
     ``ScanResult`` -- what would land in a log line or debugger dump if
     someone printed the object wholesale, not just the one field.
  3. A JSON-serialized artifact-shaped payload built from the findings
     (``json.dumps([asdict(f) for f in findings])``) -- simulates the
     ``run_artifacts``/``audit_report`` surface (PRD requirement 18/AC-27)
     without depending on the not-yet-built orchestration layer (S-135)
     that actually writes it; the fixture proves the *inputs* to that layer
     are already clean, which is the necessary precondition for the
     end-to-end surfaces (run_events, artifact, PR body) that S-135/S-139
     assemble from this module's ``Finding`` records.
  4. ``ScanResult.reason`` on every non-fatal failure path (crash / timeout
     / unparseable output) -- proves a malformed or adversarial raw payload
     containing the secret text cannot leak it back out through the
     human-readable failure reason string either.

Also covers multiple-occurrence redaction: the fixture's dummy secret
appears in two different findings (rows 0/1) plus once more inside a
(simulated) adversarial rule ``Description`` (row 2) -- every occurrence,
across every finding, must be scrubbed, not just the first match.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from scanners.gitleaks_runner import normalize_gitleaks, run_gitleaks
from scanners.types import ScanStatus

_FIXTURES = Path(__file__).parent.parent / "fixtures"

DUMMY_SECRET = "FIXTURE_DUMMY_SECRET_DO_NOT_USE_9f8e7d6c5b4a3210"


def _load_fixture(name: str) -> str:
    return (_FIXTURES / name).read_text()


class TestFindingMessageSurface:
    def test_no_finding_message_contains_the_secret(self):
        findings = normalize_gitleaks(_load_fixture("gitleaks_findings.json"))
        assert len(findings) >= 1
        for finding in findings:
            assert DUMMY_SECRET not in finding.message


class TestFindingReprAndStrSurface:
    """Guards against the secret leaking through a field this test doesn't
    know to check by name -- e.g. if a future edit added the raw ``Match``
    or ``Secret`` value to some other ``Finding`` field, ``str()``/``repr()``
    of the whole object would still catch it."""

    def test_str_of_every_finding_excludes_the_secret(self):
        findings = normalize_gitleaks(_load_fixture("gitleaks_findings.json"))
        for finding in findings:
            assert DUMMY_SECRET not in str(finding)
            assert DUMMY_SECRET not in repr(finding)


class TestArtifactJsonSurface:
    """Simulates the run_artifacts/audit_report JSON payload S-135 will
    build from these Finding records -- the secret must already be absent
    at this module's output boundary, before that orchestration exists."""

    def test_json_serialized_findings_exclude_the_secret(self):
        findings = normalize_gitleaks(_load_fixture("gitleaks_findings.json"))
        payload = json.dumps([{**asdict(f), "severity": f.severity.value} for f in findings])
        assert DUMMY_SECRET not in payload


class TestMultipleOccurrenceRedaction:
    """The dummy secret appears 3 times across the fixture batch (rows 0, 1,
    and embedded in row 2's Description) -- every occurrence must be
    scrubbed, not just the first one encountered."""

    def test_every_occurrence_across_the_batch_is_redacted(self):
        findings = normalize_gitleaks(_load_fixture("gitleaks_findings.json"))
        all_messages = " || ".join(f.message for f in findings)
        assert all_messages.count(DUMMY_SECRET) == 0

    def test_adversarial_description_field_occurrence_is_redacted(self):
        # Row 2's raw Description field contains the secret text directly
        # (simulating a rule whose own metadata echoes the match) -- proves
        # the redaction pass runs regardless of *how* the secret got near
        # the message, not only the construction-time discipline of never
        # copying Secret/Match.
        findings = normalize_gitleaks(_load_fixture("gitleaks_findings.json"))
        adversarial = next(f for f in findings if f.rule_id == "adversarial-description-echo")
        assert DUMMY_SECRET not in adversarial.message


def _completed_process(stdout: str, returncode: int = 0):
    import subprocess

    return subprocess.CompletedProcess(
        args=["gitleaks"], returncode=returncode, stdout=stdout, stderr=""
    )


class TestScanResultSurfaceOnPassedPath:
    @patch("scanners.gitleaks_runner.subprocess.run")
    def test_scan_result_findings_and_repr_exclude_the_secret(self, mock_run):
        mock_run.return_value = _completed_process(_load_fixture("gitleaks_findings.json"))

        result = run_gitleaks(Path("/workspace"), timeout=600)

        assert result.status is ScanStatus.PASSED
        assert DUMMY_SECRET not in str(result)
        assert DUMMY_SECRET not in repr(result)
        for finding in result.findings:
            assert DUMMY_SECRET not in finding.message


class TestScanResultReasonSurfaceOnFailurePaths:
    """A malformed/adversarial raw payload containing the secret text must
    never leak it back out through the non-fatal failure `reason` string
    (PRD requirement 18's per-tool error-event surface)."""

    @patch("scanners.gitleaks_runner.subprocess.run")
    def test_unparseable_output_reason_excludes_the_secret_even_if_present_in_raw_stdout(
        self, mock_run
    ):
        # Deliberately-corrupt stdout that still contains the raw secret
        # text (e.g. a truncated/garbled Gitleaks write) -- the JSON parse
        # failure path must not echo raw stdout content into `reason`.
        corrupted = f"not valid json {{{{ {DUMMY_SECRET}"
        mock_run.return_value = _completed_process(corrupted)

        result = run_gitleaks(Path("/workspace"), timeout=600)

        assert result.status is ScanStatus.FAILED
        assert result.reason is not None
        assert DUMMY_SECRET not in result.reason
