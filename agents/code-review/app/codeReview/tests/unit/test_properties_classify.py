"""
RT-02 (S-206) — classification property tactic, seed 408001, 3,000 iterations.

Paths are drawn from segment pools (lockfile names, ``dist``/``build``,
near-miss names, ``workstream/<kind>-x.md``, Unicode, deep nesting). Properties:

- ``classify`` is total and deterministic;
- prefixing ``dist/`` to a reviewed path makes it name-only;
- appending ``.txt`` to a lockfile name makes it reviewed;
- adding a name-only file never changes the changed-line count;
- adding a reviewed file increases it by exactly its additions + deletions.
"""

from __future__ import annotations

import random

from context.diff import LOCKFILE_NAMES, changed_lines, classify, path_reason
from github_client import PullFile
from tests.helpers.prng import Tactic, tactic_seed

SEED = tactic_seed(408, 1)
ITERATIONS = 3000

DIRS = [
    "src",
    "dist",
    "build",
    "distribution",
    "rebuild",
    "workstream",
    "docs",
    "apps",
    "web",
    "ünïcödé",
    "日本",
    "a b",
    "__snapshots__",
    "node_modules",
]
NAMES = [
    *sorted(LOCKFILE_NAMES),
    "lockfile.md",
    "pnpm-lock.yaml.txt",
    "Cargo.lock.bak",
    "app.py",
    "index.js",
    "a.min.js",
    "b.min.css",
    "c.js.map",
    "t.snap",
    "README.min.md",
    "tasks-x.md",
    "planner-state-x.md",
    "decisions-x.md",
    "research-x.md",
    "specification-x.md",
    "fidelity-report-S-1.md",
    "tasks.md",
    "ファイル.txt",
    "dist",
    "build",
]


def _path(rng: random.Random) -> str:
    depth = rng.choice([0, 0, 1, 1, 2, 3, 6])
    return "/".join([*(rng.choice(DIRS) for _ in range(depth)), rng.choice(NAMES)])


def _file(rng: random.Random, path: str) -> PullFile:
    has_patch = rng.random() < 0.9
    add, dele = rng.randint(0, 200), rng.randint(0, 200)
    status = rng.choice(["added", "modified", "removed", "renamed"])
    return PullFile(path, status, add, dele, patch="@@" if has_patch else None)


def test_rt02_classification_properties():
    tactic = Tactic.from_env(SEED, ITERATIONS)
    rng = tactic.rng()
    for i in range(tactic.iterations):
        files = [_file(rng, _path(rng)) for _ in range(rng.randint(0, 6))]
        extra = _file(rng, _path(rng))
        if not tactic.selected(i):
            continue
        ctx = tactic.context(i, (files, extra))

        first, second = classify(files), classify(list(files))
        assert first == second, ctx
        assert len(first.reviewed) + len(first.name_only) == len(files), ctx

        for f in files:
            reason = path_reason(f.filename)
            if reason is None and f.patch is not None:
                assert path_reason("dist/" + f.filename) == "generated", ctx
            base = f.filename.rsplit("/", 1)[-1]
            if base in LOCKFILE_NAMES and path_reason(f.filename) == "lockfile":
                assert path_reason(f.filename + ".txt") != "lockfile", ctx

        before = changed_lines(first)
        after_cls = classify([*files, extra])
        after = changed_lines(after_cls)
        if after_cls.reviewed and after_cls.reviewed[-1] is extra:
            assert after == before + extra.additions + extra.deletions, ctx
        else:
            assert after == before, ctx


def test_rt02_lockfile_plus_txt_is_reviewed_when_no_other_rule_applies():
    for name in sorted(LOCKFILE_NAMES):
        assert path_reason(f"src/{name}.txt") is None
