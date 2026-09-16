"""
Component tests for PR creation (`pull_request.py`) with mocked git/gh CLIs
(spec §8.9, PRD requirements 38-41, story S-139).

Scenarios:
  - Idempotency: `existing_pr` finds/does not find a `security/fix-*` PR
    (mocked `gh pr list`).
  - `open_pr_if_needed` short-circuits when a PR already exists — no
    branch, no push, no new PR (PRD AC-22).
  - Happy path: branch/commit/push/create in order, URL returned.
  - `create_pr` uses `--body-file`, never inline `--body` (AC-17 groundwork).
  - Commit message is the fixed Conventional Commits string (req 39).
  - Branch name follows `security/fix-<UTC timestamp>` (req 38).
  - Never pushes to the default branch (req 40).
  - Push failure scrubs the token from the raised error.
  - Token supplied via GH_TOKEN env / credential helper, never in argv or a
    remote URL.

All `subprocess.run` calls are mocked — no real `git`/`gh` process ever
runs.
"""

from __future__ import annotations

import json
import subprocess

import pytest

import pull_request as pr

TOKEN = "ghs_SUPERSECRETTOKEN123"


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["x"], returncode=returncode, stdout=stdout, stderr="")


# ---------------------------------------------------------------------------
# Idempotency: existing_pr (req 41)
# ---------------------------------------------------------------------------


class TestExistingPr:
    def test_returns_url_when_security_fix_branch_pr_exists(self, monkeypatch):
        prs = [
            {"url": "https://github.com/o/r/pull/9", "headRefName": "security/fix-20260101-000000"},
            {"url": "https://github.com/o/r/pull/8", "headRefName": "feature/other"},
        ]
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed(json.dumps(prs)))
        assert pr.existing_pr("/ws", TOKEN) == "https://github.com/o/r/pull/9"

    def test_returns_none_when_no_security_fix_branch_pr(self, monkeypatch):
        prs = [{"url": "https://github.com/o/r/pull/8", "headRefName": "feature/other"}]
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed(json.dumps(prs)))
        assert pr.existing_pr("/ws", TOKEN) is None

    def test_returns_none_on_empty_output(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _completed(""))
        assert pr.existing_pr("/ws", TOKEN) is None

    def test_gh_token_passed_via_env_not_argv(self, monkeypatch):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["env"] = kwargs.get("env")
            return _completed("[]")

        monkeypatch.setattr(subprocess, "run", fake_run)
        pr.existing_pr("/ws", TOKEN)
        assert all(TOKEN not in part for part in captured["cmd"])
        assert captured["env"]["GH_TOKEN"] == TOKEN

    def test_list_failure_raises_scrubbed(self, monkeypatch):
        def fake_run(*a, **k):
            raise subprocess.CalledProcessError(1, ["gh"], stderr=f"boom {TOKEN}")

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(pr.PullRequestError) as ei:
            pr.existing_pr("/ws", TOKEN)
        assert TOKEN not in str(ei.value)


# ---------------------------------------------------------------------------
# open_pr_if_needed — idempotent short-circuit (AC-22)
# ---------------------------------------------------------------------------


class TestOpenPrIfNeeded:
    def test_existing_pr_short_circuits_no_second_branch_or_pr(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pr, "existing_pr", lambda ws, token: "https://github.com/o/r/pull/7")
        monkeypatch.setattr(
            pr, "create_pr", lambda *a, **k: pytest.fail("create_pr should not run")
        )
        result = pr.open_pr_if_needed(str(tmp_path), TOKEN, "main", "BODY")
        assert result.existed is True
        assert result.created is False
        assert result.url == "https://github.com/o/r/pull/7"
        assert result.branch is None

    def test_new_pr_created_when_no_existing_pr(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pr, "existing_pr", lambda ws, token: None)
        monkeypatch.setattr(pr, "create_pr", lambda *a, **k: "https://github.com/o/r/pull/99")
        result = pr.open_pr_if_needed(str(tmp_path), TOKEN, "main", "BODY")
        assert result.created is True
        assert result.existed is False
        assert result.url == "https://github.com/o/r/pull/99"
        assert result.branch is not None and result.branch.startswith("security/fix-")


# ---------------------------------------------------------------------------
# create_pr — happy path and CLI contract
# ---------------------------------------------------------------------------


class TestCreatePr:
    def test_happy_path_returns_url(self, monkeypatch, tmp_path):
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[0] == "gh":
                return _completed("https://github.com/o/r/pull/42\n")
            return _completed("")

        monkeypatch.setattr(subprocess, "run", fake_run)
        url = pr.create_pr(str(tmp_path), TOKEN, "main", "BODY", branch="security/fix-x")
        assert url == "https://github.com/o/r/pull/42"

        git_cmds = [c for c in calls if c[0] == "git"]
        assert ["git", "checkout", "-b", "security/fix-x"] in git_cmds
        assert ["git", "add", "-A"] in git_cmds
        assert any(c[:3] == ["git", "commit", "-m"] for c in git_cmds)

    def test_uses_body_file_never_inline(self, monkeypatch, tmp_path):
        gh_cmd = {}

        def fake_run(cmd, **kwargs):
            if cmd[0] == "gh" and "pr" in cmd and "create" in cmd:
                gh_cmd["cmd"] = cmd
            return _completed("https://github.com/o/r/pull/1\n")

        monkeypatch.setattr(subprocess, "run", fake_run)
        pr.create_pr(str(tmp_path), TOKEN, "main", "THE BODY", branch="security/fix-x")

        assert "--body-file" in gh_cmd["cmd"]
        assert "--body" not in gh_cmd["cmd"]
        idx = gh_cmd["cmd"].index("--body-file")
        assert gh_cmd["cmd"][idx + 1].endswith(".md")

    def test_commit_message_is_conventional(self, monkeypatch, tmp_path):
        commit_msgs = []

        def fake_run(cmd, **kwargs):
            if cmd[:3] == ["git", "commit", "-m"]:
                commit_msgs.append(cmd[3])
            if cmd[0] == "gh":
                return _completed("https://github.com/o/r/pull/1\n")
            return _completed("")

        monkeypatch.setattr(subprocess, "run", fake_run)
        pr.create_pr(str(tmp_path), TOKEN, "main", "B", branch="security/fix-x")
        assert commit_msgs == ["fix(security): automated mechanical security fixes"]

    def test_never_pushes_to_default_branch(self, monkeypatch, tmp_path):
        pushed_branches = []

        def fake_run(cmd, **kwargs):
            if cmd[0] == "git" and "push" in cmd:
                pushed_branches.append(cmd[-1])
            if cmd[0] == "gh":
                return _completed("https://github.com/o/r/pull/1\n")
            return _completed("")

        monkeypatch.setattr(subprocess, "run", fake_run)
        pr.create_pr(str(tmp_path), TOKEN, "main", "B", branch="security/fix-y")
        assert pushed_branches == ["security/fix-y"]
        assert "main" not in pushed_branches

    def test_branch_default_uses_security_fix_prefix(self, monkeypatch, tmp_path):
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if cmd[0] == "gh":
                return _completed("https://github.com/o/r/pull/1\n")
            return _completed("")

        monkeypatch.setattr(subprocess, "run", fake_run)
        pr.create_pr(str(tmp_path), TOKEN, "main", "B")
        checkout_cmd = next(c for c in calls if c[:2] == ["git", "checkout"])
        assert checkout_cmd[3].startswith("security/fix-")


# ---------------------------------------------------------------------------
# Push failure — token scrubbed
# ---------------------------------------------------------------------------


class TestPushFailureScrubbed:
    def test_push_error_scrubs_token(self, monkeypatch, tmp_path):
        def fake_run(cmd, **kwargs):
            if cmd[0] == "git" and "push" in cmd:
                raise subprocess.CalledProcessError(
                    1, ["git", "push"], stderr=f"fatal: auth failed for {TOKEN}"
                )
            return _completed("")

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(pr.PullRequestError) as ei:
            pr.create_pr(str(tmp_path), TOKEN, "main", "B", branch="security/fix-z")
        assert TOKEN not in str(ei.value)
        assert ei.value.code == "PUSH_FAILED"

    def test_credential_helper_no_token_in_remote(self, monkeypatch, tmp_path):
        push_cmd = {}

        def fake_run(cmd, **kwargs):
            if cmd[0] == "git" and "push" in cmd:
                push_cmd["cmd"] = cmd
            return _completed("")

        monkeypatch.setattr(subprocess, "run", fake_run)
        pr._push_with_credential_helper(str(tmp_path), TOKEN, "security/fix-z")
        assert "origin" in push_cmd["cmd"]
        assert not any(part.startswith("https://") for part in push_cmd["cmd"])
        helper_parts = [p for p in push_cmd["cmd"] if "credential.helper" in p]
        assert helper_parts and TOKEN in helper_parts[0]


# ---------------------------------------------------------------------------
# Body-file content round-trip
# ---------------------------------------------------------------------------


class TestBodyFileContent:
    def test_body_file_written_with_content(self, monkeypatch, tmp_path):
        seen_body = {}

        def fake_run(cmd, **kwargs):
            if cmd[0] == "gh" and "--body-file" in cmd:
                path = cmd[cmd.index("--body-file") + 1]
                with open(path, encoding="utf-8") as f:
                    seen_body["content"] = f.read()
                return _completed("https://github.com/o/r/pull/1\n")
            return _completed("")

        monkeypatch.setattr(subprocess, "run", fake_run)
        body = "## Summary\n\nlots of detail"
        pr.create_pr(str(tmp_path), TOKEN, "main", body, branch="security/fix-x")
        assert seen_body["content"] == body

    def test_body_file_deleted_after_pr_create(self, monkeypatch, tmp_path):
        written_path = {}

        def fake_run(cmd, **kwargs):
            if cmd[0] == "gh" and "--body-file" in cmd:
                written_path["path"] = cmd[cmd.index("--body-file") + 1]
                return _completed("https://github.com/o/r/pull/1\n")
            return _completed("")

        monkeypatch.setattr(subprocess, "run", fake_run)
        pr.create_pr(str(tmp_path), TOKEN, "main", "B", branch="security/fix-x")
        import os

        assert not os.path.exists(written_path["path"])
