"""Tests for the pipeline span that carries the llipe.* attributes (issue #62, AC3).

Background — why this file exists
--------------------------------
`emission.py` sets the `llipe.*` attributes on `trace.get_current_span()`. In the
deployed agent that call resolved to the `POST /invocations` SERVER span, which
AgentCore ends as soon as the non-blocking entrypoint returns (~3 ms), while the
pipeline keeps running on a worker thread for minutes. An ended span reports
`is_recording() == False`, so `emit_span_attributes()` returned early and every
attribute was silently dropped. Verified against a live run: the `spans` stream in
the agent's log group contained zero records carrying `llipe.subject.id`.

`tests/test_emission.py` did not catch this because each test starts its own live
span before calling `emit_span_attributes()`. The gap was that *production* never
opened a span the worker thread could write to.

The fix: `_run_pipeline` opens its own span around the pipeline body, so the
attributes land on a span that is still recording when the `finally` block runs and
is therefore exported.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

# Ensure the agent source is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _make_provider() -> tuple[Any, Any]:
    """Create a TracerProvider wired to an InMemorySpanExporter."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


def _payload() -> dict[str, Any]:
    return {"session_id": "span-test-001", "repo": "llipe/memo-cli"}


def _no_updates_mocks() -> list[Any]:
    """Patches that drive the pipeline down the `no_updates` path."""
    return [
        patch("main.get_github_token", return_value="fake-token"),
        patch("main.clone_repo"),
        patch("main.default_branch", return_value="main"),
        patch("main._ensure_pnpm_version"),
        patch("main.install_deps"),
        patch("main.snapshot_lockfile_packages", return_value={}),
        patch("main.run_audit", return_value={}),
        patch("main.update_packages", return_value=""),
        patch("main.has_changes", return_value=False),
        patch("main.stamp_outcome"),
    ]


def _run_with(provider: Any, extra_patches: list[Any]) -> None:
    """Run _run_pipeline with main's tracer bound to the test provider."""
    import main

    tracer = provider.get_tracer("test-tracer")

    with (
        patch.object(main.app, "complete_async_task"),
        patch("main.trace.get_tracer", return_value=tracer),
    ):
        for p in extra_patches:
            p.start()
        try:
            main._run_pipeline(_payload(), 1)
        finally:
            for p in reversed(extra_patches):
                p.stop()


class TestPipelineSpanExists:
    """The worker thread must open its own recording span."""

    def test_pipeline_span_is_exported(self) -> None:
        """A span is exported for the pipeline run."""
        provider, exporter = _make_provider()
        try:
            _run_with(provider, _no_updates_mocks())
            provider.force_flush()

            spans = exporter.get_finished_spans()
            assert len(spans) >= 1, "pipeline must export at least one span"
        finally:
            provider.shutdown()

    def test_llipe_attributes_land_on_exported_span(self) -> None:
        """AC3: the exported span carries all four llipe.* attributes.

        This is the assertion that fails against the pre-fix code, because the
        attributes were written to an already-ended span and dropped.
        """
        provider, exporter = _make_provider()
        try:
            _run_with(provider, _no_updates_mocks())
            provider.force_flush()

            spans = exporter.get_finished_spans()
            carrying = [s for s in spans if "llipe.subject.id" in dict(s.attributes or {})]
            assert carrying, "no exported span carries llipe.subject.id"

            attrs = dict(carrying[0].attributes or {})
            assert attrs["llipe.subject.id"] == "llipe/memo-cli"
            # no_updates → success / none / ""
            assert attrs["llipe.run.status"] == "success"
            assert attrs["llipe.outcome.type"] == "none"
            assert attrs["llipe.outcome.url"] == ""
        finally:
            provider.shutdown()

    def test_span_is_still_recording_when_attributes_are_emitted(self) -> None:
        """Regression guard on the actual root cause.

        The span emission happens in a `finally` block; that block must run while
        the span is still open. If the span were ended first, `is_recording()`
        would be False and emission would no-op.
        """
        provider, _exporter = _make_provider()
        observed: list[bool] = []

        import emission as emission_mod

        real_emit = emission_mod.emit_span_attributes

        def spy(**kwargs: Any) -> None:
            from opentelemetry import trace

            observed.append(trace.get_current_span().is_recording())
            real_emit(**kwargs)

        try:
            _run_with(provider, [*_no_updates_mocks(), patch("main.emit_span_attributes", spy)])
            provider.force_flush()

            assert observed, "emit_span_attributes was never called"
            assert observed[0] is True, "span was not recording when attributes were emitted"
        finally:
            provider.shutdown()


class TestPipelineSpanOnFailurePaths:
    """The span must be exported with attributes on every terminal path."""

    def test_attributes_exported_on_exception_path(self) -> None:
        """An unhandled pipeline exception still yields a span with failed status."""
        provider, exporter = _make_provider()
        try:
            _run_with(
                provider,
                [
                    patch("main.get_github_token", side_effect=RuntimeError("boom")),
                    patch("main.stamp_outcome"),
                ],
            )
            provider.force_flush()

            spans = exporter.get_finished_spans()
            carrying = [s for s in spans if "llipe.run.status" in dict(s.attributes or {})]
            assert carrying, "no exported span carries llipe.run.status"
            attrs = dict(carrying[0].attributes or {})
            assert attrs["llipe.run.status"] == "failed"
            assert attrs["llipe.outcome.type"] == "none"
            assert attrs["llipe.outcome.url"] == ""
        finally:
            provider.shutdown()

    def test_attributes_exported_on_subprocess_error_path(self) -> None:
        """CalledProcessError path also emits a failed-status span."""
        provider, exporter = _make_provider()
        try:
            _run_with(
                provider,
                [
                    patch(
                        "main.get_github_token",
                        side_effect=subprocess.CalledProcessError(1, "git clone"),
                    ),
                    patch("main.stamp_outcome"),
                ],
            )
            provider.force_flush()

            spans = exporter.get_finished_spans()
            carrying = [s for s in spans if "llipe.run.status" in dict(s.attributes or {})]
            assert carrying
            assert dict(carrying[0].attributes or {})["llipe.run.status"] == "failed"
        finally:
            provider.shutdown()


class TestPipelineSpanTraceCorrelation:
    """The pipeline span must join the invocation's trace, not start a new one."""

    def test_pipeline_span_joins_ambient_trace(self) -> None:
        """When a span is in context, the pipeline span shares its trace ID.

        `opentelemetry-instrumentation-threading` copies the OTel context into the
        worker thread, so in production the invocation trace is already ambient.
        This test simulates that and asserts the pipeline span does not orphan
        itself into a separate trace.
        """
        provider, exporter = _make_provider()
        try:
            tracer = provider.get_tracer("test-tracer")
            with tracer.start_as_current_span("POST /invocations") as server_span:
                expected_trace_id = server_span.get_span_context().trace_id
                _run_with(provider, _no_updates_mocks())

            provider.force_flush()
            spans = exporter.get_finished_spans()
            carrying = [s for s in spans if "llipe.subject.id" in dict(s.attributes or {})]
            assert carrying, "no exported span carries llipe.subject.id"
            assert carrying[0].get_span_context().trace_id == expected_trace_id
        finally:
            provider.shutdown()

    def test_async_task_completion_still_fires(self) -> None:
        """Wrapping the pipeline in a span must not break the /ping lifecycle."""
        import main

        provider, _ = _make_provider()
        tracer = provider.get_tracer("test-tracer")
        patches = _no_updates_mocks()

        try:
            with (
                patch.object(main.app, "complete_async_task") as mock_complete,
                patch("main.trace.get_tracer", return_value=tracer),
            ):
                for p in patches:
                    p.start()
                try:
                    main._run_pipeline(_payload(), 4242)
                finally:
                    for p in reversed(patches):
                        p.stop()

            mock_complete.assert_called_once_with(4242)
        finally:
            provider.shutdown()
