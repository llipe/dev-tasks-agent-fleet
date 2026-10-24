"""L1 tests for the root wrapper and the ``setpriv`` drop in the image (S-182 task 3.17; D-110).

AgentCore runs the container with ``no_new_privs`` set, so setuid ``sudo``
can't run (probe run 1). D-110: the wrapper runs as **root** and starts every
``fixer`` process through ``setpriv``, which drops privileges and works under
``no_new_privs``. ``sudo`` and its sudoers file are gone; ``/work/wrapper`` and
``/work/secrets`` are ``root:root`` 0700.

The behaviour (uid/gid 10002, no groups, no capabilities, ``NoNewPrivs: 1``,
no way back to root, ``/proc/<root pid>/environ`` and ``mem`` unreadable) is
asserted against the built image by ``scripts/image-smoke.sh``, with
``--security-opt no-new-privileges`` to emulate AgentCore. These tests pin the
committed Dockerfile and the smoke assertions.
"""

from __future__ import annotations

import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[2]
DOCKERFILE = PKG / "Dockerfile"
SMOKE = PKG / "scripts" / "image-smoke.sh"
SETPRIV = "setpriv --reuid=10002 --regid=10002 --clear-groups --inh-caps=-all --no-new-privs"


def _apt_packages() -> set[str]:
    text = DOCKERFILE.read_text()
    m = re.search(r"apt-get install -y --no-install-recommends(.*?)&&", text, re.DOTALL)
    assert m, "no apt-get install line"
    return set(m.group(1).replace("\\", " ").split())


def _instructions(keyword: str) -> list[str]:
    return [
        line.strip()
        for line in DOCKERFILE.read_text().splitlines()
        if line.strip().startswith(keyword + " ")
    ]


class TestDockerfile:
    def test_no_sudo_package_or_sudoers(self):
        assert "sudo" not in _apt_packages()
        text = DOCKERFILE.read_text()
        assert "sudoers" not in text
        assert "visudo" not in text
        assert not (PKG / "sudoers-bug-fix").exists()

    def test_util_linux_for_setpriv(self):
        assert "util-linux" in _apt_packages()
        assert "command -v setpriv" in DOCKERFILE.read_text()

    def test_wrapper_runs_as_root(self):
        users = _instructions("USER")
        assert users == ["USER root"], users
        assert "ENV HOME=/root" in DOCKERFILE.read_text()

    def test_no_wrapper_os_user(self):
        # The wrapper is root; a second unprivileged user would be unused.
        text = DOCKERFILE.read_text()
        assert 'useradd --uid "${WRAPPER_UID}"' not in text
        assert "WRAPPER_UID" not in text

    def test_fixer_user_kept(self):
        text = DOCKERFILE.read_text()
        assert "ARG FIXER_UID=10002" in text
        assert re.search(r"useradd --uid \"\$\{FIXER_UID\}\" --gid fixer", text)

    def test_wrapper_dirs_are_root_0700(self):
        assert "install -d -o root -g root -m 0700 /work/wrapper /work/secrets" in (
            DOCKERFILE.read_text()
        )

    def test_fixer_dirs_kept(self):
        assert "install -d -o fixer -g fixer -m 0755 /work/repo /work/out" in (
            DOCKERFILE.read_text()
        )


class TestSmokeAssertions:
    """The smoke script asserts the D-110 behaviour against the built image."""

    def test_uses_the_exact_setpriv_drop(self):
        assert SETPRIV in SMOKE.read_text()

    def test_emulates_agentcore_no_new_privileges(self):
        assert "--security-opt no-new-privileges" in SMOKE.read_text()

    def test_default_user_is_root(self):
        assert "default user is root" in SMOKE.read_text()

    def test_checks_identity_caps_and_nnp(self):
        text = SMOKE.read_text()
        for field in ("Uid", "Gid", "Groups", "CapEff", "CapPrm", "CapInh", "CapAmb"):
            assert field in text, field
        assert "NoNewPrivs" in text
        assert "10002" in text

    def test_checks_no_way_back_to_root(self):
        text = SMOKE.read_text()
        assert "os.setuid(0)" in text
        assert "su root" in text
        assert "--reuid=0" in text

    def test_checks_root_proc_environ_and_mem(self):
        text = SMOKE.read_text()
        assert "/environ" in text
        assert "/mem" in text

    def test_checks_no_sudo_binary(self):
        text = SMOKE.read_text()
        assert "command -v sudo" in text
        assert "/etc/sudoers.d/bug-fix" in text

    def test_checks_the_production_sweep(self):
        assert "Sandbox().sweep()" in SMOKE.read_text()

    def test_no_sudo_era_assertions_left(self):
        text = SMOKE.read_text()
        assert "sudo -n -u fixer" not in text
        assert "as_user wrapper" not in text
