"""Integration test: poll /ping during a simulated long task (S-007, sub-task 7.8).

Verifies:
- /ping returns HealthyBusy while the pipeline runs
- /ping returns Healthy after completion
"""

import threading
import time
from typing import Any
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def _block_pipeline():  # type: ignore[no-untyped-def]
    """Fixture that makes _run_pipeline block until released."""
    barrier = threading.Event()
    started = threading.Event()

    def blocking_pipeline(payload: Any, task_id: int) -> None:
        from main import app

        started.set()
        try:
            barrier.wait(timeout=10)
        finally:
            app.complete_async_task(task_id)

    with patch("main._run_pipeline", side_effect=blocking_pipeline):
        yield started, barrier


@pytest.fixture
def agent_client():  # type: ignore[no-untyped-def]
    """Create a test client for the AgentCore app's ASGI server."""
    from main import app

    # BedrockAgentCoreApp extends Starlette, so it IS the ASGI app
    return TestClient(app, raise_server_exceptions=False)


class TestPingStatusDuringPipeline:
    """7.8: Poll /ping during a simulated long task."""

    def test_ping_healthy_busy_during_pipeline(
        self, agent_client: TestClient, _block_pipeline: tuple[threading.Event, threading.Event]
    ) -> None:
        """While pipeline runs, /ping must return HealthyBusy."""
        started, barrier = _block_pipeline

        # Invoke the entrypoint to start the background pipeline
        response = agent_client.post(
            "/invocations",
            json={"repo_url": "https://github.com/test/repo"},
            headers={"X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": "int-test-session"},
        )
        assert response.status_code == 200

        # Wait for the pipeline thread to start
        assert started.wait(timeout=5), "Pipeline thread did not start"
        # Small delay to ensure the async task is registered
        time.sleep(0.1)

        # Poll /ping — should be HealthyBusy
        ping_resp = agent_client.get("/ping")
        assert ping_resp.status_code == 200
        ping_data = ping_resp.json()
        assert ping_data["status"] == "HealthyBusy", f"Expected HealthyBusy, got {ping_data}"

        # Release the pipeline
        barrier.set()
        # Give the thread time to call complete_async_task
        time.sleep(0.2)

        # Now /ping should be Healthy
        ping_resp = agent_client.get("/ping")
        assert ping_resp.status_code == 200
        ping_data = ping_resp.json()
        assert ping_data["status"] == "Healthy", (
            f"Expected Healthy after completion, got {ping_data}"
        )

    def test_ping_healthy_after_pipeline_exception(self, agent_client: TestClient) -> None:
        """After pipeline raises an exception, /ping should return Healthy."""
        completed = threading.Event()

        def crashing_pipeline(payload: Any, task_id: int) -> None:
            from main import app

            try:
                raise RuntimeError("Pipeline exploded")
            except Exception:
                print("[test] simulated pipeline crash")
            finally:
                app.complete_async_task(task_id)
                completed.set()

        with patch("main._run_pipeline", side_effect=crashing_pipeline):
            response = agent_client.post(
                "/invocations",
                json={"repo_url": "https://github.com/test/repo"},
                headers={"X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": "crash-session"},
            )
            assert response.status_code == 200

        # Wait for the thread to complete
        assert completed.wait(timeout=5)
        time.sleep(0.1)

        ping_resp = agent_client.get("/ping")
        assert ping_resp.status_code == 200
        ping_data = ping_resp.json()
        assert ping_data["status"] == "Healthy", f"Expected Healthy after crash, got {ping_data}"
