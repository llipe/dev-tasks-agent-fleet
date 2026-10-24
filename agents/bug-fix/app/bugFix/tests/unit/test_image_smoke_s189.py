"""L1 pins for the S-189 fix round's image-smoke additions (#371).

The behaviour is asserted against the built image by ``scripts/image-smoke.sh``;
these tests pin that the assertions are there:

- QA-189-01: ``fs.protected_hardlinks`` and ``fs.protected_symlinks`` are 1
  inside the image (the run-time preflight only logs them);
- gap 6: a tree with a symlink ``zlink`` and a file under ``zlink/`` goes
  through ``materialize`` with the image's GNU tar, and nothing is written
  through the link.
"""

from __future__ import annotations

from pathlib import Path

PKG = Path(__file__).resolve().parents[2]
SMOKE = PKG / "scripts" / "image-smoke.sh"


def test_smoke_asserts_both_link_protection_sysctls_are_one():
    text = SMOKE.read_text()
    assert "/proc/sys/fs/protected_hardlinks" in text
    assert "/proc/sys/fs/protected_symlinks" in text
    assert "fs.protected_hardlinks and fs.protected_symlinks are 1" in text


def test_smoke_runs_the_symlink_then_file_tree_through_gnu_tar():
    text = SMOKE.read_text()
    assert "GNU tar" in text
    assert "zlink" in text
    assert "outside_empty=True" in text
    # The second line is tested on its own: fsck is off for this clone only.
    assert "CLONE_FSCK_ARGS = ()" in text
    assert "fsck_refuses=True" in text
