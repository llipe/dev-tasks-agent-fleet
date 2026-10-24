"""
Seeded PRNG helper shared by every property tactic (test plan §2.1, §9, G-6).

Built on ``random.Random(seed)`` so it adds no dependency (neither sibling has
``hypothesis``). The seed per tactic is ``<issue number> x 1000 + k``.

Replay one failing iteration with::

    PRNG_SEED=<seed> PRNG_ITER=<i> make -C agents/code-review/app/codeReview test-unit -k <test>

The generator stream is shared across iterations, so a tactic generates every
input up to ``i`` and checks only the selected one; this keeps a replayed
iteration byte-identical to the original run.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass

ENV_SEED = "PRNG_SEED"
ENV_ITER = "PRNG_ITER"


def tactic_seed(issue: int, k: int) -> int:
    """Return the fixed seed for tactic ``k`` of ``issue`` (``issue x 1000 + k``)."""
    if not 1 <= k <= 999:
        raise ValueError(f"tactic index k must be in 1..999, got {k}")
    return issue * 1000 + k


@dataclass(frozen=True)
class Tactic:
    """One property tactic run: seed, iteration count, and optional replay index."""

    seed: int
    iterations: int
    only_iter: int | None = None

    @classmethod
    def from_env(cls, default_seed: int, iterations: int) -> Tactic:
        seed = int(os.environ.get(ENV_SEED, default_seed))
        raw_iter = os.environ.get(ENV_ITER)
        only = int(raw_iter) if raw_iter is not None else None
        return cls(seed=seed, iterations=iterations, only_iter=only)

    @property
    def replaying(self) -> bool:
        return self.only_iter is not None

    def rng(self) -> random.Random:
        return random.Random(self.seed)

    def selected(self, i: int) -> bool:
        return self.only_iter is None or i == self.only_iter

    def context(self, i: int, value: object) -> str:
        return (
            f"seed={self.seed} iter={i} input={value!r} "
            f"(replay: {ENV_SEED}={self.seed} {ENV_ITER}={i})"
        )
