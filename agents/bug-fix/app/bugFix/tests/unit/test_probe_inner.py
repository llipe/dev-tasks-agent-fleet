"""L1 tests for ``probe_inner.py``, the fixer-side half of the probe (S-182 task 3.4).

Each subcommand prints one JSON object; the wrapper (``probe.py``) turns it
into a verdict. Network, sockets and subprocesses are faked; file checks use
``tmp_path``. The PAT scan receives a SHA-256 digest only.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import urllib.error
from email.message import Message
from pathlib import Path

import pytest

import probe_inner

PAT = "ghp_" + "Q" * 36


class _Resp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestNet:
    def test_blocked_everywhere(self, monkeypatch):
        def _url(url, timeout):
            raise urllib.error.URLError("Tunnel connection failed: 403")

        def _sock(addr, timeout):
            raise OSError(101, "Network is unreachable")

        monkeypatch.setattr(probe_inner.urllib.request, "urlopen", _url)
        monkeypatch.setattr(probe_inner.socket, "create_connection", _sock)
        d = probe_inner.cmd_net("http://169.254.169.254/", "169.254.169.254", "80")
        assert d["http"] == "blocked"
        assert d["tcp"] == "blocked"
        assert "URLError" in d["detail"]

    def test_reachable(self, monkeypatch):
        monkeypatch.setattr(probe_inner.urllib.request, "urlopen", lambda url, timeout: _Resp())

        class _S:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(probe_inner.socket, "create_connection", lambda a, timeout: _S())
        d = probe_inner.cmd_net("https://example.com/", "example.com", "443")
        assert d == {"url": "https://example.com/", "http": "status:200", "tcp": "connected"}

    def test_proxy_403_is_marked(self, monkeypatch):
        headers = Message()
        headers["X-Proxy-Error"] = "blocked-by-sandbox-runtime"

        def _url(url, timeout):
            raise urllib.error.HTTPError(url, 403, "Forbidden", headers, None)

        def _sock(addr, timeout):
            raise OSError("no route")

        monkeypatch.setattr(probe_inner.urllib.request, "urlopen", _url)
        monkeypatch.setattr(probe_inner.socket, "create_connection", _sock)
        d = probe_inner.cmd_net("https://example.com/", "example.com", "443")
        assert d["http"] == "status:403"
        assert d["proxy_error"] is True
        assert d["tcp"] == "blocked"


class TestFiles:
    def test_proc_of_missing_pid_is_unreadable(self):
        d = probe_inner.cmd_proc("999999999")
        assert d["visible"] is False
        assert d["environ"].startswith("unreadable:")
        assert d["mem"].startswith("unreadable:")

    def test_read_helper(self, tmp_path):
        f = tmp_path / "f"
        f.write_bytes(b"abc")
        assert probe_inner._read(str(f)) == "readable:3"

    def test_env_lists_names_only(self, monkeypatch):
        monkeypatch.setenv("SENTINEL_NAME_7F3A", "sentinel-value-7f3a")
        d = probe_inner.cmd_env()
        assert "SENTINEL_NAME_7F3A" in d["names"]
        assert "sentinel-value-7f3a" not in json.dumps(d)

    def test_write_and_read(self, tmp_path):
        target = tmp_path / "x"
        assert probe_inner.cmd_write(str(target)) == {"written": True}
        assert probe_inner.cmd_write(str(tmp_path / "no" / "x"))["written"] is False
        assert probe_inner.cmd_read(str(target)) == {"readable": True}
        assert probe_inner.cmd_read(str(tmp_path)) == {"readable": True}
        missing = probe_inner.cmd_read(str(tmp_path / "missing"))
        assert missing["readable"] is False and missing["error"] == "ENOENT"

    def test_scan_counts_only_the_digest(self, tmp_path, monkeypatch):
        digest = hashlib.sha256(PAT.encode()).hexdigest()
        (tmp_path / "a.txt").write_text(f"token={PAT}\nother=ghp_{'Z' * 36}\n")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.txt").write_text(PAT)
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "skipped").write_text(PAT)
        (tmp_path / "link").symlink_to(tmp_path / "a.txt")
        monkeypatch.delenv("GITHUB_PROJECTS_TOKEN", raising=False)
        d = probe_inner.cmd_scan(digest, str(tmp_path))
        assert d["matches"] == 2
        assert d["files"] == 2
        assert probe_inner.cmd_scan("0" * 64, str(tmp_path))["matches"] == 0

    def test_scan_sees_the_environment(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LEAKED", PAT)
        d = probe_inner.cmd_scan(hashlib.sha256(PAT.encode()).hexdigest(), str(tmp_path))
        assert d["matches"] >= 1

    def test_scan_stops_at_the_file_cap(self, tmp_path, monkeypatch):
        monkeypatch.setattr(probe_inner, "_SCAN_MAX_FILES", 2)
        for i in range(5):
            (tmp_path / f"f{i}").write_text("x")
        assert probe_inner.cmd_scan("0" * 64, str(tmp_path))["files"] == 2


class TestRepoAndRefs:
    def test_mkrepo_and_refs(self, tmp_path):
        repo = tmp_path / "probe-repo"
        d = probe_inner.cmd_mkrepo(str(repo))
        assert d["ok"] is True
        settings = json.loads((repo / ".claude" / "settings.json").read_text())
        assert "Bash(git push:*)" in settings["permissions"]["allow"]
        assert settings["sandbox"]["enabled"] is False
        assert probe_inner.cmd_refs(d["remote"]) == {"refs": 0}

        # A push that got through would land on the bare remote.
        subprocess.run(["git", "push", "-q", "origin", "HEAD:main"], cwd=repo, check=True)
        assert probe_inner.cmd_refs(d["remote"])["refs"] == 1

    def test_refs_counts_packed_refs(self, tmp_path):
        g = tmp_path / "r.git"
        (g / "refs").mkdir(parents=True)
        (g / "packed-refs").write_text("# pack-refs\nabc refs/heads/main\n^def\n")
        assert probe_inner.cmd_refs(str(g)) == {"refs": 1}


class TestSubprocesses:
    def test_sudo_rc(self, monkeypatch):
        class R:
            returncode = 1

        monkeypatch.setattr(probe_inner.subprocess, "run", lambda *a, **k: R())
        assert probe_inner.cmd_sudo() == {"rc": 1}

    def test_sudo_missing(self, monkeypatch):
        def _missing(*a, **k):
            raise FileNotFoundError("sudo")

        monkeypatch.setattr(probe_inner.subprocess, "run", _missing)
        assert probe_inner.cmd_sudo()["rc"] == -1

    def test_tool(self):
        d = probe_inner.cmd_tool("/bin/sh", "-c", "echo hi; exit 3")
        assert d["rc"] == 3
        assert "hi" in d["out"]

    def test_tool_missing(self):
        assert probe_inner.cmd_tool("/nonexistent/tool")["rc"] == -1


class TestMain:
    def test_dispatch_prints_one_json_line(self, capsys):
        assert probe_inner.main(["probe_inner.py", "env"]) == 0
        line = capsys.readouterr().out.strip()
        assert "names" in json.loads(line)

    def test_unknown_subcommand(self, capsys):
        assert probe_inner.main(["probe_inner.py", "rm-rf"]) == 2
        assert json.loads(capsys.readouterr().out)["error"] == "unknown subcommand"

    def test_errors_are_data(self, capsys):
        assert probe_inner.main(["probe_inner.py", "proc", "not-a-pid"]) == 0
        assert "ValueError" in json.loads(capsys.readouterr().out)["error"]


@pytest.mark.parametrize("name", sorted(probe_inner.COMMANDS))
def test_every_subcommand_is_callable(name):
    assert callable(probe_inner.COMMANDS[name])


def test_probe_inner_is_stdlib_only():
    # It runs as fixer with `python3 -I`; it must not import wrapper modules.
    text = Path(probe_inner.__file__).read_text()
    for mod in ("requests", "boto3", "scrubber", "credentials", "config", "sandbox", "probe "):
        assert f"import {mod}" not in text
