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


class TestResolve:
    def test_resolves_localhost_and_lists_the_hosts_and_nsswitch_lines(self, tmp_path, monkeypatch):
        hosts = tmp_path / "hosts"
        hosts.write_text("# x\n127.0.0.1\tlocalhost\n10.0.0.5 box\n")
        nsswitch = tmp_path / "nsswitch.conf"
        nsswitch.write_text("passwd: files\n# hosts: dns\nhosts:   files myhostname dns\n")
        monkeypatch.setattr(
            probe_inner.socket,
            "getaddrinfo",
            lambda host, *a, **k: [
                (2, 1, 6, "", ("127.0.0.1", 0)),
                (2, 2, 17, "", ("127.0.0.1", 0)),
                (10, 1, 6, "", ("::1", 0, 0, 0)),
            ],
        )
        d = probe_inner.cmd_resolve("localhost", str(hosts), str(nsswitch))
        # Order kept: the check needs to see which family comes first.
        assert d["addrs"] == ["127.0.0.1", "::1"]
        assert d["hosts"] == ["127.0.0.1\tlocalhost"]
        assert d["nsswitch"] == "files myhostname dns"

    def test_failure_is_reported_not_raised(self, tmp_path, monkeypatch):
        def _fail(*a, **k):
            raise probe_inner.socket.gaierror(-3, "Temporary failure in name resolution")

        monkeypatch.setattr(probe_inner.socket, "getaddrinfo", _fail)
        d = probe_inner.cmd_resolve(
            "localhost", str(tmp_path / "missing"), str(tmp_path / "missing-nss")
        )
        assert d["addrs"] == []
        assert "name resolution" in d["error"]
        assert d["hosts"] == []
        assert d["nsswitch"] is None

    def test_registered(self):
        assert probe_inner.COMMANDS["resolve"] is probe_inner.cmd_resolve


class TestSubprocesses:
    def test_tool(self):
        d = probe_inner.cmd_tool("/bin/sh", "-c", "echo hi; exit 3")
        assert d["rc"] == 3
        assert "hi" in d["out"]

    def test_tool_missing(self):
        assert probe_inner.cmd_tool("/nonexistent/tool")["rc"] == -1


STATUS_FIXER = """Name:\tpython3
NoNewPrivs:\t1
Uid:\t10002\t10002\t10002\t10002
Gid:\t10002\t10002\t10002\t10002
Groups:\t
CapInh:\t0000000000000000
CapPrm:\t0000000000000000
CapEff:\t0000000000000000
CapBnd:\t000001ffffffffff
CapAmb:\t0000000000000000
Seccomp:\t2
"""


class TestIds:
    """``ids``: the identity the setpriv drop produced, from /proc/self/status (D-110)."""

    def test_parses_status(self, tmp_path):
        f = tmp_path / "status"
        f.write_text(STATUS_FIXER)
        d = probe_inner.cmd_ids(str(f))
        assert d["uid"] == [10002, 10002, 10002, 10002]
        assert d["gid"] == [10002, 10002, 10002, 10002]
        assert d["groups"] == []
        assert d["cap_eff"] == "0000000000000000"
        assert d["cap_prm"] == "0000000000000000"
        assert d["cap_inh"] == "0000000000000000"
        assert d["cap_amb"] == "0000000000000000"
        assert d["cap_bnd"] == "000001ffffffffff"
        assert d["no_new_privs"] == 1
        assert d["seccomp"] == "2"

    def test_groups_listed(self, tmp_path):
        f = tmp_path / "status"
        f.write_text(STATUS_FIXER.replace("Groups:\t\n", "Groups:\t10002 27\n"))
        assert probe_inner.cmd_ids(str(f))["groups"] == [10002, 27]

    def test_missing_fields_are_none(self, tmp_path):
        f = tmp_path / "status"
        f.write_text("Name:\tx\n")
        d = probe_inner.cmd_ids(str(f))
        assert d["uid"] is None and d["no_new_privs"] is None and d["cap_eff"] is None

    def test_unreadable_status(self, tmp_path):
        d = probe_inner.cmd_ids(str(tmp_path / "missing"))
        assert d["error"].startswith("unreadable:")


class _R:
    def __init__(self, rc: int, err: str = "") -> None:
        self.returncode = rc
        self.stdout = ""
        self.stderr = err


class TestEscalate:
    """``escalate``: every way back to root must fail for fixer (D-110)."""

    def _fake(self, monkeypatch, *, setuid_ok=False, rc=1, nnp="1"):
        calls: list[list[str]] = []

        def _setid(_v):
            if not setuid_ok:
                raise PermissionError(1, "Operation not permitted")

        def _run(argv, **kw):
            calls.append(list(argv))
            return _R(rc, "su: Authentication failure")

        monkeypatch.setattr(probe_inner.os, "setuid", _setid)
        monkeypatch.setattr(probe_inner.os, "setgid", _setid)
        monkeypatch.setattr(probe_inner.subprocess, "run", _run)
        monkeypatch.setattr(
            probe_inner, "_status_fields", lambda path="/proc/self/status": {"NoNewPrivs": nnp}
        )
        monkeypatch.setattr(probe_inner.shutil, "which", lambda name: None)
        return calls

    def test_all_refused(self, monkeypatch):
        calls = self._fake(monkeypatch)
        d = probe_inner.cmd_escalate()
        assert d["setuid0"] == "EPERM"
        assert d["setgid0"] == "EPERM"
        assert d["su"]["rc"] == 1
        assert d["setpriv_root"]["rc"] == 1
        assert d["no_new_privs"] == 1
        assert d["sudo_on_path"] is False
        assert ["su", "root", "-c", "true"] in calls
        assert ["setpriv", "--reuid=0", "--regid=0", "--", "true"] in calls

    def test_setuid_success_is_reported(self, monkeypatch):
        self._fake(monkeypatch, setuid_ok=True)
        assert probe_inner.cmd_escalate()["setuid0"] == "ok"

    def test_missing_binary(self, monkeypatch):
        self._fake(monkeypatch)

        def _missing(*a, **k):
            raise FileNotFoundError("su")

        monkeypatch.setattr(probe_inner.subprocess, "run", _missing)
        d = probe_inner.cmd_escalate()
        assert d["su"]["rc"] == -1
        assert "FileNotFoundError" in d["su"]["err"]


class TestUserns:
    """``userns``: can bwrap create user+pid+net namespaces here? (D-110)"""

    def test_reports_bwrap_and_unshare(self, monkeypatch, tmp_path):
        calls: list[list[str]] = []

        def _run(argv, **kw):
            calls.append(list(argv))
            if argv[0] == "bwrap":
                return _R(1, "bwrap: No permissions to create a new namespace")
            return _R(0)

        monkeypatch.setattr(probe_inner.subprocess, "run", _run)
        knob = tmp_path / "max_user_namespaces"
        knob.write_text("15000\n")
        monkeypatch.setattr(
            probe_inner,
            "USERNS_SYSCTLS",
            {"max_user_namespaces": str(knob), "unprivileged_userns_clone": str(tmp_path / "x")},
        )
        d = probe_inner.cmd_userns()
        assert d["bwrap"]["rc"] == 1
        assert "No permissions" in d["bwrap"]["err"]
        assert d["unshare"]["rc"] == 0
        assert d["sysctl"] == {"max_user_namespaces": "15000", "unprivileged_userns_clone": None}
        bwrap = next(c for c in calls if c[0] == "bwrap")
        for flag in ("--unshare-user", "--unshare-pid", "--unshare-net"):
            assert flag in bwrap
        unshare = next(c for c in calls if c[0] == "unshare")
        for flag in ("--user", "--pid", "--net", "--fork"):
            assert flag in unshare


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
