"""L1 tests for the S-189 fix round's repo-gate changes (#371, PR #458):

- QA-189-04: a ``packageManager`` field needs its own lockfile; yarn and bun
  are refused with their own item, never as "missing lockfile";
- DF-189-08: the makefile GNU make would read (``GNUmakefile``, ``makefile``,
  ``Makefile``, first that exists) is the one the gate reads;
- DF-189-05: the ``repo_gate`` reply uses a fixed phrase per item, and the
  ``install`` phrase says "missing install target" (D-112).
"""

from __future__ import annotations

import os

import pytest

from refusal import REPLY_PREFIX, REPO_GATE_ITEMS, REPO_GATE_PHRASES, Refusal, reply_line
from tests.unit.test_toolchain import DEV, GATES, MK_OK, MapReader, pkg
from toolchain import (
    DEVELOPER_MD,
    LOCKFILE_ITEM,
    MAKEFILE_NAMES,
    MISS_ITEMS,
    UNSUPPORTED_PM_ITEM,
    DirReader,
    Stack,
    check_repo_gate,
    detect_stack,
    makefile_name,
)


def _js(field: str | None = None, *locks: str) -> dict[str, str]:
    extra = {"packageManager": field} if field else {}
    files = {DEVELOPER_MD: DEV, "package.json": pkg(GATES, **extra)}
    for lock in locks:
        files[lock] = "lock"
    return files


# ---------------------------------------------------------------------------
# QA-189-04: packageManager versus the lockfile; yarn and bun
# ---------------------------------------------------------------------------


class TestPackageManagerLockfile:
    @pytest.mark.parametrize(
        ("field", "locks", "manager"),
        [
            ("pnpm@9.1.0", ("pnpm-lock.yaml",), "pnpm"),
            ("npm@10.8.0", ("package-lock.json",), "npm"),
            ("pnpm@9.1.0", ("pnpm-lock.yaml", "package-lock.json"), "pnpm"),
            (None, ("pnpm-lock.yaml", "yarn.lock"), "pnpm"),
            (None, ("package-lock.json", "bun.lockb"), "npm"),
        ],
    )
    def test_a_matching_lockfile_passes(self, field, locks, manager):
        gate = check_repo_gate(MapReader(_js(field, *locks)))
        assert gate.ok, gate.summary
        assert gate.toolchain is not None
        assert gate.toolchain.manager == manager

    @pytest.mark.parametrize(
        ("field", "locks"),
        [
            ("pnpm@9.1.0", ()),
            ("pnpm@9.1.0", ("package-lock.json",)),
            ("npm@10.8.0", ()),
            ("npm@10.8.0", ("pnpm-lock.yaml",)),
        ],
    )
    def test_a_field_without_its_own_lockfile_is_a_lockfile_miss(self, field, locks):
        gate = check_repo_gate(MapReader(_js(field, *locks)))
        assert [m.item for m in gate.missing] == [LOCKFILE_ITEM]
        assert gate.toolchain is None

    @pytest.mark.parametrize(
        ("field", "locks"),
        [
            ("yarn@4.1.0", ("yarn.lock",)),
            ("yarn@1.22.0", ()),
            ("bun@1.1.0", ("bun.lockb",)),
            ("yarn@4.1.0", ("pnpm-lock.yaml",)),  # corepack would run yarn
            ("deno@2.0.0", ("pnpm-lock.yaml",)),
            (None, ("yarn.lock",)),
            (None, ("bun.lockb",)),
            (None, ("bun.lock",)),
        ],
    )
    def test_yarn_and_bun_are_an_unsupported_manager(self, field, locks):
        gate = check_repo_gate(MapReader(_js(field, *locks)))
        assert [m.item for m in gate.missing] == [UNSUPPORTED_PM_ITEM]
        assert gate.toolchain is None
        assert "supported package manager (pnpm or npm)" in gate.summary

    def test_no_lockfile_at_all_is_still_the_lockfile_miss(self):
        gate = check_repo_gate(MapReader(_js(None)))
        assert [m.item for m in gate.missing] == [LOCKFILE_ITEM]

    def test_the_new_item_is_in_both_closed_sets(self):
        assert UNSUPPORTED_PM_ITEM == "supported package manager (pnpm or npm)"
        assert UNSUPPORTED_PM_ITEM in MISS_ITEMS
        assert UNSUPPORTED_PM_ITEM in REPO_GATE_ITEMS


# ---------------------------------------------------------------------------
# DF-189-08: the makefile GNU make reads
# ---------------------------------------------------------------------------

ONLY_TEST = "test:\n\t@true\n"


class TestMakefileNames:
    def test_the_order_is_gnu_makes(self):
        assert MAKEFILE_NAMES == ("GNUmakefile", "makefile", "Makefile")

    @pytest.mark.parametrize("name", ["GNUmakefile", "makefile", "Makefile"])
    def test_any_of_the_three_names_is_python(self, name):
        files = {DEVELOPER_MD: DEV, name: MK_OK}
        reader = MapReader(files)
        assert detect_stack(reader) is Stack.PYTHON
        assert makefile_name(reader) == name
        assert check_repo_gate(reader).ok

    @pytest.mark.parametrize(
        ("present", "used"),
        [
            (("GNUmakefile", "Makefile"), "GNUmakefile"),
            (("makefile", "Makefile"), "makefile"),
            (("GNUmakefile", "makefile", "Makefile"), "GNUmakefile"),
        ],
    )
    def test_the_first_in_gnu_order_is_the_one_read(self, present, used):
        """The others are ignored, as make ignores them: a full ``Makefile``
        beside a ``GNUmakefile`` with only ``test`` is judged by the latter."""
        files = {DEVELOPER_MD: DEV}
        for name in present:
            files[name] = MK_OK if name != used else ONLY_TEST
        gate = check_repo_gate(MapReader(files))
        assert {m.item for m in gate.missing} == {"lint", "format-check", "typecheck", "install"}

    def test_a_symlinked_gnumakefile_is_not_skipped_for_makefile(self, tmp_path):
        """make follows the link; the gate can't read through it, so it reads
        nothing rather than a Makefile make would never use."""
        (tmp_path / ".claude" / "agents").mkdir(parents=True)
        (tmp_path / DEVELOPER_MD).write_text(DEV)
        (tmp_path / "Makefile").write_text(MK_OK)
        (tmp_path / "elsewhere.mk").write_text(MK_OK)
        os.symlink("elsewhere.mk", tmp_path / "GNUmakefile")
        reader = DirReader(str(tmp_path))
        assert makefile_name(reader) == "GNUmakefile"
        gate = check_repo_gate(reader)
        assert not gate.ok
        assert "install" in {m.item for m in gate.missing}


# ---------------------------------------------------------------------------
# DF-189-05: fixed reply phrases
# ---------------------------------------------------------------------------


class TestReplyPhrases:
    def test_install_says_missing_install_target(self):
        line = reply_line(Refusal("repo_gate", detail="install"), 12)
        assert "missing install target" in line
        assert line == (
            REPLY_PREFIX + "this repository is missing install target (the Makefile target "
            "`install`), which bug-fix needs before it can work here."
        )

    def test_every_item_has_a_fixed_phrase(self):
        assert set(REPO_GATE_PHRASES) == set(REPO_GATE_ITEMS)
        for item, phrase in REPO_GATE_PHRASES.items():
            assert phrase.startswith("missing "), item
            assert "{" not in phrase, item

    @pytest.mark.parametrize("item", REPO_GATE_ITEMS)
    def test_the_reply_is_the_template_and_the_phrase_only(self, item):
        line = reply_line(Refusal("repo_gate", detail=item), None)
        assert line == (
            REPLY_PREFIX + f"this repository is {REPO_GATE_PHRASES[item]}, "
            "which bug-fix needs before it can work here."
        )

    @pytest.mark.parametrize(
        ("item", "words"),
        [
            ("format:check", "`package.json` script `format:check`"),
            ("format-check", "Makefile target `format-check`"),
            ("lockfile", "`pnpm-lock.yaml`"),
            ("supported package manager (pnpm or npm)", "yarn and bun"),
        ],
    )
    def test_phrases_say_what_kind_of_thing_is_missing(self, item, words):
        assert words in reply_line(Refusal("repo_gate", detail=item), None)
