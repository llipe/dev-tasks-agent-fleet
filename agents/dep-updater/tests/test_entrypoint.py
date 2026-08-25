"""Tests for the non-blocking entrypoint pattern (S-007).

Verifies:
- Entrypoint returns immediately without running the pipeline (7.5)
- complete_async_task invoked on both success and exception (7.6)
- Worker thread started as daemon (7.7)
"""

import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch


class TestEntrypointReturnsImmediately:
    """7.5: Entrypoint returns without running the pipeline."""

    def test_entrypoint_returns_within_one_second(self) -> None:
        """The entrypoint must return within 1 second, not blocking on pipeline."""
        from main import app, dep_update

        mock_context = MagicMock()
        mock_context.session_id = "test-session-123"

        payload = {"repo_url": "https://github.com/test/repo"}

        # Use an event to prove the pipeline hasn't completed before entrypoint returns
        pipeline_started = threading.Event()

        def slow_pipeline(p: object, tid: int) -> None:
            pipeline_started.set()
            time.sleep(5)  # Simulates a long pipeline

        with (
            patch.object(app, "add_async_task", return_value=42) as mock_add,
            patch("main._run_pipeline", side_effect=slow_pipeline),
        ):
            start = time.monotonic()
            dep_update(payload, mock_context)
            elapsed = time.monotonic() - start

        assert elapsed < 1.0, f"Entrypoint took {elapsed:.2f}s, must be < 1s"
        # The pipeline was dispatched to a thread but the entrypoint returned first
        mock_add.assert_called_once()

    def test_entrypoint_returns_session_id(self) -> None:
        """The entrypoint should acknowledge with the session_id."""
        from main import app, dep_update

        mock_context = MagicMock()
        mock_context.session_id = "session-abc-xyz"

        payload = {"repo_url": "https://github.com/test/repo"}

        with (
            patch.object(app, "add_async_task", return_value=99),
            patch("main._run_pipeline"),
        ):
            result = dep_update(payload, mock_context)

        assert result["session_id"] == "session-abc-xyz"
        assert result["status"] == "accepted"

    def test_entrypoint_does_not_call_pipeline_synchronously(self) -> None:
        """Pipeline body must not execute on the entrypoint thread."""
        from main import app, dep_update

        mock_context = MagicMock()
        mock_context.session_id = "test-session"

        # If pipeline ran synchronously, this would block forever
        payload = {"repo_url": "https://github.com/test/repo"}

        call_log: list[str] = []

        def fake_pipeline(p: Any, tid: int) -> None:
            call_log.append("pipeline_started")
            time.sleep(5)  # Would block if synchronous

        with (
            patch.object(app, "add_async_task", return_value=1),
            patch("main._run_pipeline", side_effect=fake_pipeline),
        ):
            start = time.monotonic()
            dep_update(payload, mock_context)
            elapsed = time.monotonic() - start

        # Entrypoint returned quickly — pipeline didn't block it
        assert elapsed < 1.0


class TestCompleteAsyncTask:
    """7.6: complete_async_task invoked on both success and exception."""

    def test_complete_async_task_called_on_success(self) -> None:
        """complete_async_task must fire when pipeline succeeds."""
        from main import _run_pipeline, app

        task_id = 42
        payload = {"repo_url": "https://github.com/test/repo"}

        with (
            patch.object(app, "complete_async_task") as mock_complete,
            patch("main.get_github_token", return_value="fake-token"),
            patch("main.clone_repo"),
            patch("main.default_branch", return_value="main"),
            patch("main._ensure_pnpm_version"),
            patch("main.install_deps"),
            patch("main.snapshot_lockfile_packages", return_value={}),
            patch("main.run_audit", return_value={}),
            patch("main.update_packages", return_value=""),
            patch("main.has_changes", return_value=False),
        ):
            _run_pipeline(payload, task_id)

        mock_complete.assert_called_once_with(task_id)

    def test_complete_async_task_called_on_exception(self) -> None:
        """complete_async_task must fire even when pipeline raises."""
        from main import _run_pipeline, app

        task_id = 99
        payload = {"repo_url": "https://github.com/test/repo"}

        with (
            patch.object(app, "complete_async_task") as mock_complete,
            patch("main.get_github_token", side_effect=RuntimeError("boom")),
        ):
            # Should not propagate the exception out
            _run_pipeline(payload, task_id)

        mock_complete.assert_called_once_with(task_id)

    def test_complete_async_task_called_on_subprocess_error(self) -> None:
        """complete_async_task must fire on CalledProcessError."""
        import subprocess

        from main import _run_pipeline, app

        task_id = 77
        payload = {"repo_url": "https://github.com/test/repo"}

        with (
            patch.object(app, "complete_async_task") as mock_complete,
            patch(
                "main.get_github_token",
                side_effect=subprocess.CalledProcessError(1, "git clone"),
            ),
        ):
            _run_pipeline(payload, task_id)

        mock_complete.assert_called_once_with(task_id)


class TestDaemonThread:
    """7.7: Worker thread started as daemon."""

    def test_worker_thread_is_daemon(self) -> None:
        """The thread running _run_pipeline must be a daemon thread."""
        from main import app, dep_update

        mock_context = MagicMock()
        mock_context.session_id = "test-session"

        payload = {"repo_url": "https://github.com/test/repo"}

        threads_started: list[threading.Thread] = []

        def capture_start(self: threading.Thread) -> None:
            threads_started.append(self)
            # Don't actually start — we just want to inspect the thread

        with (
            patch.object(app, "add_async_task", return_value=1),
            patch.object(app, "complete_async_task"),
            patch("main._run_pipeline"),
            patch.object(threading.Thread, "start", capture_start),
        ):
            dep_update(payload, mock_context)

        assert len(threads_started) == 1
        assert threads_started[0].daemon is True, "Worker thread must be a daemon"

    def test_worker_thread_name_contains_session(self) -> None:
        """The worker thread should have a descriptive name."""
        from main import app, dep_update

        mock_context = MagicMock()
        mock_context.session_id = "my-session-42"

        payload = {"repo_url": "https://github.com/test/repo"}

        threads_started: list[threading.Thread] = []

        def capture_start(self: threading.Thread) -> None:
            threads_started.append(self)

        with (
            patch.object(app, "add_async_task", return_value=1),
            patch.object(app, "complete_async_task"),
            patch("main._run_pipeline"),
            patch.object(threading.Thread, "start", capture_start),
        ):
            dep_update(payload, mock_context)

        assert len(threads_started) == 1
        assert "my-session-42" in (threads_started[0].name or "")
