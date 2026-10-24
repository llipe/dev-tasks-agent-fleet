"""L1 tests for the narrow sudo rule and its Dockerfile wiring (S-182 task 3.16; D-109).

The image runs as non-root ``wrapper`` (uid 10001). The only way it can start
a process as ``fixer`` (uid 10002) is one sudoers rule, ``wrapper ALL=(fixer)
NOPASSWD: ALL``, plus ``Defaults env_reset`` and a fixed ``secure_path``. The
file is installed as ``/etc/sudoers.d/bug-fix``, root-owned, mode 0440, and
checked with ``visudo -cf`` at build time. ``fixer`` gets no rule at all.

The behaviour (``sudo -u fixer id -u`` is 10002, ``fixer`` can't sudo,
``wrapper`` can't become root) is asserted against the built image by
``scripts/image-smoke.sh``; these tests pin the committed file and the
Dockerfile lines that install it.
"""

from __future__ import annotations

import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[2]
SUDOERS = PKG / "sudoers-bug-fix"
DOCKERFILE = PKG / "Dockerfile"
SMOKE = PKG / "scripts" / "image-smoke.sh"


def _rules() -> list[str]:
    """Non-comment, non-blank lines of the sudoers file."""
    lines = []
    for raw in SUDOERS.read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


class TestSudoersFile:
    def test_exactly_one_user_rule_and_two_defaults(self):
        rules = _rules()
        defaults = [r for r in rules if r.startswith("Defaults")]
        user_rules = [r for r in rules if not r.startswith("Defaults")]
        assert user_rules == ["wrapper ALL=(fixer) NOPASSWD: ALL"]
        assert len(defaults) == 2

    def test_env_reset(self):
        assert "Defaults env_reset" in _rules()

    def test_fixed_secure_path(self):
        paths = [r for r in _rules() if r.startswith("Defaults secure_path=")]
        assert len(paths) == 1
        value = paths[0].split("=", 1)[1].strip('"')
        parts = value.split(":")
        assert parts, "secure_path is empty"
        for part in parts:
            # Absolute system directories only: nothing fixer or wrapper owns.
            assert part.startswith("/"), part
            assert not part.startswith(("/home", "/work", "/tmp")), part

    def test_runas_is_fixer_only(self):
        # wrapper may become fixer and nobody else: no ALL, root or a group.
        for rule in _rules():
            if rule.startswith("Defaults"):
                continue
            m = re.match(r"^(\S+)\s+ALL=\(([^)]*)\)", rule)
            assert m, rule
            assert m.group(1) == "wrapper"
            assert m.group(2) == "fixer"

    def test_fixer_has_no_rule(self):
        for rule in _rules():
            assert not rule.startswith(("fixer", "%fixer", "ALL", "%"))

    def test_no_env_widening_options(self):
        text = SUDOERS.read_text()
        for opt in ("!env_reset", "env_keep", "setenv", "SETENV", "!secure_path", "env_file"):
            assert opt not in text, f"{opt} widens what wrapper can pass to fixer"


class TestDockerfileInstall:
    def test_sudo_installed(self):
        text = DOCKERFILE.read_text()
        assert re.search(r"apt-get install[^\n]*(\\\n[^\n]*)*\bsudo\b", text), "sudo not installed"

    def test_sudoers_file_copied_with_root_0440(self):
        text = DOCKERFILE.read_text()
        assert "COPY sudoers-bug-fix /etc/sudoers.d/bug-fix" in text
        assert "chown root:root /etc/sudoers.d/bug-fix" in text
        assert "chmod 0440 /etc/sudoers.d/bug-fix" in text

    def test_sudoers_validated_at_build(self):
        assert "visudo -cf /etc/sudoers.d/bug-fix" in DOCKERFILE.read_text()


class TestSmokeAssertions:
    """The smoke script asserts the D-109 behaviour against the built image."""

    def test_smoke_checks_switch_to_fixer_uid(self):
        text = SMOKE.read_text()
        assert "sudo -n -u fixer id -u" in text
        assert "10002" in text

    def test_smoke_checks_fixer_cannot_sudo(self):
        assert "as_user fixer 'sudo -n true'" in SMOKE.read_text()

    def test_smoke_checks_wrapper_cannot_become_root(self):
        assert "as_user wrapper 'sudo -n -u root true'" in SMOKE.read_text()

    def test_smoke_checks_sudoers_owner_and_mode(self):
        text = SMOKE.read_text()
        assert "/etc/sudoers.d/bug-fix" in text
        assert "root:root 440" in text
