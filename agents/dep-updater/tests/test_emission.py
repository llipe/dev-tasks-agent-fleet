"""Tests for the llipe.* span attribute emission module (S-010).

Verifies:
- 10.5: Unit test — result-to-attribute mapping for all five results
- 10.6: Unit test — attributes emitted on exception path
- 10.7: Integration test — in-memory OTel exporter asserts four attributes on root span
- 10.8: Integration test — confirm root span annotation from worker thread (not a child span)
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

# Ensure the agent source is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ─── Unit Tests: Result-to-Attribute Mapping (10.5) ──────────────────────────


class TestResultToAttributeMapping:
    """10.5: result-to-attribute mapping for all five results."""

    def test_success_pr_created(self) -> None:
        """success (PR created) → status=success, type=pr, url=<PR URL>."""
        from emission import map_result

        result = map_result("success", pr_url="https://github.com/org/repo/pull/42")
        assert result.status == "success"
        assert result.outcome_type == "pr"
        assert result.outcome_url == "https://github.com/org/repo/pull/42"

    def test_no_updates(self) -> None:
        """no_updates → status=success, type=none, url=""."""
        from emission import map_result

        result = map_result("no_updates", pr_url=None)
        assert result.status == "success"
        assert result.outcome_type == "none"
        assert result.outcome_url == ""

    def test_pr_already_open(self) -> None:
        """pr_already_open → status=success, type=pr, url=<existing PR URL>."""
        from emission import map_result

        result = map_result("pr_already_open", pr_url="https://github.com/org/repo/pull/10")
        assert result.status == "success"
        assert result.outcome_type == "pr"
        assert result.outcome_url == "https://github.com/org/repo/pull/10"

    def test_tests_failing(self) -> None:
        """tests_failing → status=failed, type=none, url=""."""
        from emission import map_result

        result = map_result("tests_failing", pr_url=None)
        assert result.status == "failed"
        assert result.outcome_type == "none"
        assert result.outcome_url == ""

    def test_error(self) -> None:
        """error → status=failed, type=none, url=""."""
        from emission import map_result

        result = map_result("error", pr_url=None)
        assert result.status == "failed"
        assert result.outcome_type == "none"
        assert result.outcome_url == ""

    def test_outcome_url_empty_not_absent_for_no_updates(self) -> None:
        """outcome_url MUST be empty string, never None, when no URL exists."""
        from emission import map_result

        result = map_result("no_updates", pr_url=None)
        assert result.outcome_url is not None
        assert result.outcome_url == ""

    def test_outcome_url_empty_not_absent_for_error(self) -> None:
        """outcome_url MUST be empty string on error path."""
        from emission import map_result

        result = map_result("error", pr_url=None)
        assert result.outcome_url is not None
        assert result.outcome_url == ""

    def test_pr_url_none_on_success_still_gives_empty(self) -> None:
        """Edge case: success result but pr_url is None → url is empty."""
        from emission import map_result

        result = map_result("success", pr_url=None)
        assert result.status == "success"
        assert result.outcome_type == "pr"
        assert result.outcome_url == ""


# ─── Unit Tests: emit_span_attributes (10.4, 10.6) ───────────────────────────


class TestEmitSpanAttributes:
    """10.4/10.6: Attributes emitted on the current span with correct values."""

    def test_emit_sets_all_four_attributes(self) -> None:
        """emit_span_attributes sets all four llipe.* attributes on the span."""
        from emission import RunResult, emit_span_attributes

        mock_span = MagicMock()
        mock_span.is_recording.return_value = True

        with patch("emission.trace.get_current_span", return_value=mock_span):
            result = RunResult(
                status="success", outcome_type="pr", outcome_url="https://example.com/pr/1"
            )
            emit_span_attributes(result=result, subject_id="owner/repo")

        # Verify all four attributes set
        calls = {c[0][0]: c[0][1] for c in mock_span.set_attribute.call_args_list}
        assert calls["llipe.subject.id"] == "owner/repo"
        assert calls["llipe.run.status"] == "success"
        assert calls["llipe.outcome.type"] == "pr"
        assert calls["llipe.outcome.url"] == "https://example.com/pr/1"

    def test_emit_uses_constants_from_generated_contract(self) -> None:
        """Attribute keys MUST come from LLIPE constants, never string literals."""
        from shared_contract import LLIPE

        from emission import RunResult, emit_span_attributes

        mock_span = MagicMock()
        mock_span.is_recording.return_value = True

        with patch("emission.trace.get_current_span", return_value=mock_span):
            result = RunResult(status="failed", outcome_type="none", outcome_url="")
            emit_span_attributes(result=result, subject_id="org/repo")

        keys_set = [c[0][0] for c in mock_span.set_attribute.call_args_list]
        assert LLIPE.SUBJECT_ID in keys_set
        assert LLIPE.RUN_STATUS in keys_set
        assert LLIPE.OUTCOME_TYPE in keys_set
        assert LLIPE.OUTCOME_URL in keys_set

    def test_emit_on_error_path(self) -> None:
        """10.6: Attributes emitted even when result is 'error' (exception path)."""
        from emission import RunResult, emit_span_attributes

        mock_span = MagicMock()
        mock_span.is_recording.return_value = True

        with patch("emission.trace.get_current_span", return_value=mock_span):
            result = RunResult(status="failed", outcome_type="none", outcome_url="")
            emit_span_attributes(result=result, subject_id="org/repo")

        calls = {c[0][0]: c[0][1] for c in mock_span.set_attribute.call_args_list}
        assert calls["llipe.run.status"] == "failed"
        assert calls["llipe.outcome.type"] == "none"
        assert calls["llipe.outcome.url"] == ""

    def test_emit_subject_id_is_normalized(self) -> None:
        """10.4: llipe.subject.id must equal the normalized subject_id."""
        from emission import RunResult, emit_span_attributes

        mock_span = MagicMock()
        mock_span.is_recording.return_value = True

        with patch("emission.trace.get_current_span", return_value=mock_span):
            result = RunResult(status="success", outcome_type="none", outcome_url="")
            emit_span_attributes(result=result, subject_id="myorg/myrepo")

        calls = {c[0][0]: c[0][1] for c in mock_span.set_attribute.call_args_list}
        assert calls["llipe.subject.id"] == "myorg/myrepo"

    def test_emit_skips_when_span_not_recording(self) -> None:
        """If span is not recording, set_attribute should not be called."""
        from emission import RunResult, emit_span_attributes

        mock_span = MagicMock()
        mock_span.is_recording.return_value = False

        with patch("emission.trace.get_current_span", return_value=mock_span):
            result = RunResult(status="success", outcome_type="none", outcome_url="")
            emit_span_attributes(result=result, subject_id="org/repo")

        mock_span.set_attribute.assert_not_called()


# ─── Integration Tests: In-Memory OTel Exporter (10.7, 10.8) ─────────────────


class TestOtelIntegration:
    """10.7/10.8: In-memory OTel exporter asserts four attributes on root span."""

    def _make_provider(self) -> tuple[Any, Any]:
        """Create a fresh TracerProvider with InMemorySpanExporter.

        Uses the provider directly (not the global) to avoid the
        'cannot override TracerProvider' limitation in tests.
        """
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        return provider, exporter

    def test_attributes_on_root_span(self) -> None:
        """10.7: All four llipe.* attributes present on the root span."""
        from emission import RunResult, emit_span_attributes

        provider, exporter = self._make_provider()

        try:
            tracer = provider.get_tracer("test-tracer")

            # Create a root span and emit attributes within it
            with tracer.start_as_current_span("root-span"):
                result = RunResult(
                    status="success",
                    outcome_type="pr",
                    outcome_url="https://github.com/org/repo/pull/1",
                )
                emit_span_attributes(result=result, subject_id="org/repo")

            # Force export
            provider.force_flush()

            spans = exporter.get_finished_spans()
            assert len(spans) == 1

            root = spans[0]
            attrs = dict(root.attributes or {})
            assert attrs["llipe.subject.id"] == "org/repo"
            assert attrs["llipe.run.status"] == "success"
            assert attrs["llipe.outcome.type"] == "pr"
            assert attrs["llipe.outcome.url"] == "https://github.com/org/repo/pull/1"
        finally:
            provider.shutdown()

    def test_root_span_annotation_from_worker_thread(self) -> None:
        """10.8: Root span is annotated from a worker thread (not a child span).

        This mirrors the real runtime: the root span is started before the
        worker thread, and the thread sets attributes on that same root span.
        """
        from opentelemetry import context, trace

        from emission import RunResult, emit_span_attributes

        provider, exporter = self._make_provider()

        try:
            tracer = provider.get_tracer("test-tracer")

            # Start root span on the main thread
            root_span = tracer.start_span("root-span")
            ctx = trace.set_span_in_context(root_span)

            # Worker thread that emits attributes on the root span
            errors: list[Exception] = []

            def worker() -> None:
                try:
                    # Attach the context containing the root span
                    token = context.attach(ctx)
                    try:
                        result = RunResult(status="failed", outcome_type="none", outcome_url="")
                        emit_span_attributes(result=result, subject_id="owner/repo")
                    finally:
                        context.detach(token)
                except Exception as e:
                    errors.append(e)

            t = threading.Thread(target=worker, daemon=True)
            t.start()
            t.join(timeout=5)

            # End the root span
            root_span.end()

            assert not errors, f"Worker thread raised: {errors}"

            provider.force_flush()
            spans = exporter.get_finished_spans()

            # Only one span (the root), not a child
            assert len(spans) == 1
            root = spans[0]
            assert root.parent is None, "Should be the root span (no parent)"

            attrs = dict(root.attributes or {})
            assert attrs["llipe.subject.id"] == "owner/repo"
            assert attrs["llipe.run.status"] == "failed"
            assert attrs["llipe.outcome.type"] == "none"
            assert attrs["llipe.outcome.url"] == ""
        finally:
            provider.shutdown()

    def test_four_attributes_always_present(self) -> None:
        """All four attributes must be present even for error/no_updates cases."""
        from emission import RunResult, emit_span_attributes

        provider, exporter = self._make_provider()

        try:
            tracer = provider.get_tracer("test-tracer")

            with tracer.start_as_current_span("root"):
                result = RunResult(status="failed", outcome_type="none", outcome_url="")
                emit_span_attributes(result=result, subject_id="x/y")

            provider.force_flush()
            spans = exporter.get_finished_spans()
            attrs = dict(spans[0].attributes or {})

            # All four keys present
            assert "llipe.subject.id" in attrs
            assert "llipe.run.status" in attrs
            assert "llipe.outcome.type" in attrs
            assert "llipe.outcome.url" in attrs
        finally:
            provider.shutdown()
