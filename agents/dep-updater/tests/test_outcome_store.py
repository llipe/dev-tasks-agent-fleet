"""Tests for outcome_store.py (S-011).

Verifies:
- 11.6: Update expression contains only two attributes (last_status, last_outcome_url)
- 11.7: Called on both success and failure paths
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestUpdateExpressionScope:
    """11.6: UpdateItem expression only updates last_status and last_outcome_url."""

    def test_update_expression_sets_exactly_two_attributes(self) -> None:
        """The UpdateExpression must set only last_status and last_outcome_url."""
        from outcome_store import stamp_outcome

        mock_table = MagicMock()

        with patch("outcome_store._get_table", return_value=mock_table):
            stamp_outcome(
                subject_id="owner/repo",
                agent_name="dep-updater",
                status="success",
                outcome_url="https://github.com/owner/repo/pull/1",
            )

        mock_table.update_item.assert_called_once()
        call_kwargs = mock_table.update_item.call_args[1]

        # Verify UpdateExpression sets exactly two attributes
        update_expr = call_kwargs["UpdateExpression"]
        assert "last_status" in update_expr
        assert "last_outcome_url" in update_expr

        # Ensure no other attributes are in the expression
        # The expression should be: SET last_status = :status, last_outcome_url = :url
        assert "enabled" not in update_expr
        assert "params" not in update_expr
        assert "last_session_id" not in update_expr
        assert "last_run_at" not in update_expr

    def test_expression_attribute_values_only_contain_status_and_url(self) -> None:
        """ExpressionAttributeValues must only have :status and :url."""
        from outcome_store import stamp_outcome

        mock_table = MagicMock()

        with patch("outcome_store._get_table", return_value=mock_table):
            stamp_outcome(
                subject_id="owner/repo",
                agent_name="dep-updater",
                status="failed",
                outcome_url="",
            )

        call_kwargs = mock_table.update_item.call_args[1]
        values = call_kwargs["ExpressionAttributeValues"]

        assert values[":status"] == "failed"
        assert values[":url"] == ""
        assert len(values) == 2, (
            f"Expected exactly 2 expression values, got {len(values)}: {values}"
        )

    def test_condition_expression_checks_item_exists(self) -> None:
        """ConditionExpression must use attribute_exists(pk) to prevent creating items."""
        from outcome_store import stamp_outcome

        mock_table = MagicMock()

        with patch("outcome_store._get_table", return_value=mock_table):
            stamp_outcome(
                subject_id="owner/repo",
                agent_name="dep-updater",
                status="success",
                outcome_url="",
            )

        call_kwargs = mock_table.update_item.call_args[1]
        condition = call_kwargs["ConditionExpression"]
        assert "attribute_exists" in condition
        assert "pk" in condition

    def test_key_uses_subject_prefix_and_agent_prefix(self) -> None:
        """Key must use SUBJECT# and AGENT# prefixes from shared contract."""
        from outcome_store import stamp_outcome

        mock_table = MagicMock()

        with patch("outcome_store._get_table", return_value=mock_table):
            stamp_outcome(
                subject_id="my-org/my-repo",
                agent_name="dep-updater",
                status="success",
                outcome_url="https://github.com/my-org/my-repo/pull/5",
            )

        call_kwargs = mock_table.update_item.call_args[1]
        key = call_kwargs["Key"]
        assert key["pk"] == "SUBJECT#my-org/my-repo"
        assert key["sk"] == "AGENT#dep-updater"


class TestCalledOnBothPaths:
    """11.7: stamp_outcome is called on both success and failure paths."""

    def test_called_on_success_path(self) -> None:
        """stamp_outcome must be called when pipeline succeeds (no_updates)."""
        from main import _run_pipeline, app

        task_id = 42
        payload = {
            "session_id": "test-session-success",
            "repo": "test-org/test-repo",
        }

        with (
            patch.object(app, "complete_async_task"),
            patch("main.get_github_token", return_value="fake-token"),
            patch("main.clone_repo"),
            patch("main.default_branch", return_value="main"),
            patch("main._ensure_pnpm_version"),
            patch("main.install_deps"),
            patch("main.snapshot_lockfile_packages", return_value={}),
            patch("main.run_audit", return_value={}),
            patch("main.update_packages", return_value=""),
            patch("main.has_changes", return_value=False),
            patch("main.emit_span_attributes"),
            patch("main.stamp_outcome") as mock_stamp,
        ):
            _run_pipeline(payload, task_id)

        mock_stamp.assert_called_once()
        call_kwargs = mock_stamp.call_args[1]
        assert call_kwargs["status"] == "success"  # no_updates maps to success
        assert call_kwargs["outcome_url"] == ""
        assert call_kwargs["subject_id"] == "test-org/test-repo"

    def test_called_on_failure_path(self) -> None:
        """stamp_outcome must be called when pipeline raises an exception."""
        from main import _run_pipeline, app

        task_id = 99
        payload = {
            "session_id": "test-session-failure",
            "repo": "test-org/test-repo",
        }

        with (
            patch.object(app, "complete_async_task"),
            patch("main.get_github_token", side_effect=RuntimeError("boom")),
            patch("main.emit_span_attributes"),
            patch("main.stamp_outcome") as mock_stamp,
        ):
            _run_pipeline(payload, task_id)

        mock_stamp.assert_called_once()
        call_kwargs = mock_stamp.call_args[1]
        assert call_kwargs["status"] == "failed"
        assert call_kwargs["outcome_url"] == ""

    def test_called_on_subprocess_error(self) -> None:
        """stamp_outcome must be called on CalledProcessError."""
        import subprocess

        from main import _run_pipeline, app

        task_id = 77
        payload = {
            "session_id": "test-session-subprocess",
            "repo": "test-org/test-repo",
        }

        with (
            patch.object(app, "complete_async_task"),
            patch(
                "main.get_github_token",
                side_effect=subprocess.CalledProcessError(1, "git clone"),
            ),
            patch("main.emit_span_attributes"),
            patch("main.stamp_outcome") as mock_stamp,
        ):
            _run_pipeline(payload, task_id)

        mock_stamp.assert_called_once()
        call_kwargs = mock_stamp.call_args[1]
        assert call_kwargs["status"] == "failed"


class TestErrorHandling:
    """11.5: Failed DynamoDB write logs error, does not mask the run result."""

    def test_dynamo_failure_does_not_propagate(self) -> None:
        """A DynamoDB write failure must not raise out of stamp_outcome."""
        from outcome_store import stamp_outcome

        mock_table = MagicMock()
        mock_table.update_item.side_effect = Exception("DynamoDB timeout")

        with patch("outcome_store._get_table", return_value=mock_table):
            # Must not raise
            stamp_outcome(
                subject_id="owner/repo",
                agent_name="dep-updater",
                status="success",
                outcome_url="",
            )

    def test_conditional_check_failed_logs_error(self) -> None:
        """When item doesn't exist (ConditionalCheckFailedException), log error."""
        from botocore.exceptions import ClientError

        from outcome_store import stamp_outcome

        mock_table = MagicMock()
        error_response = {
            "Error": {
                "Code": "ConditionalCheckFailedException",
                "Message": "The conditional request failed",
            }
        }
        mock_table.update_item.side_effect = ClientError(
            error_response, "UpdateItem"
        )

        with (
            patch("outcome_store._get_table", return_value=mock_table),
            patch("outcome_store._log_error") as mock_log,
        ):
            stamp_outcome(
                subject_id="owner/repo",
                agent_name="dep-updater",
                status="success",
                outcome_url="",
            )

        mock_log.assert_called_once()
        logged_msg = mock_log.call_args[0][0]
        assert "item" in logged_msg.lower() or "conditional" in logged_msg.lower()

    def test_general_dynamo_error_logs_error(self) -> None:
        """General DynamoDB errors log but don't raise."""
        from outcome_store import stamp_outcome

        mock_table = MagicMock()
        mock_table.update_item.side_effect = RuntimeError("Network timeout")

        with (
            patch("outcome_store._get_table", return_value=mock_table),
            patch("outcome_store._log_error") as mock_log,
        ):
            stamp_outcome(
                subject_id="owner/repo",
                agent_name="dep-updater",
                status="failed",
                outcome_url="",
            )

        mock_log.assert_called_once()


class TestNoPutItemInAgent:
    """11.4: Ensure no PutItem exists anywhere in agent code."""

    def test_no_put_item_in_outcome_store(self) -> None:
        """outcome_store.py must not contain put_item calls."""
        from pathlib import Path

        source = Path(__file__).parent.parent / "outcome_store.py"
        content = source.read_text()
        assert "put_item" not in content.lower()
        assert "PutItem" not in content
