"""
Test plan G-6 / §9 — the shared seeded PRNG helper for property tactics.

Every RT tactic seeds ``random.Random`` with ``<issue> x 1000 + k`` and can be
replayed with ``PRNG_SEED=<seed> PRNG_ITER=<i>``. These tests pin that contract.
"""

from __future__ import annotations

import pytest

from tests.helpers.prng import Tactic, tactic_seed


def test_tactic_seed_is_issue_times_1000_plus_k():
    assert tactic_seed(407, 1) == 407001
    assert tactic_seed(406, 1) == 406001


def test_tactic_seed_rejects_k_outside_1_to_999():
    with pytest.raises(ValueError):
        tactic_seed(407, 0)
    with pytest.raises(ValueError):
        tactic_seed(407, 1000)


def test_same_seed_gives_the_same_stream(monkeypatch):
    monkeypatch.delenv("PRNG_SEED", raising=False)
    monkeypatch.delenv("PRNG_ITER", raising=False)
    a = Tactic.from_env(407001, 10).rng()
    b = Tactic.from_env(407001, 10).rng()
    assert [a.random() for _ in range(5)] == [b.random() for _ in range(5)]


def test_env_overrides_seed_and_selects_one_iteration(monkeypatch):
    monkeypatch.setenv("PRNG_SEED", "123")
    monkeypatch.setenv("PRNG_ITER", "4")
    tactic = Tactic.from_env(407001, 10)
    assert tactic.seed == 123
    assert tactic.only_iter == 4
    assert [i for i in range(tactic.iterations) if tactic.selected(i)] == [4]
    assert tactic.replaying


def test_without_env_every_iteration_is_selected(monkeypatch):
    monkeypatch.delenv("PRNG_SEED", raising=False)
    monkeypatch.delenv("PRNG_ITER", raising=False)
    tactic = Tactic.from_env(407001, 7)
    assert tactic.seed == 407001
    assert all(tactic.selected(i) for i in range(7))
    assert not tactic.replaying


def test_context_names_seed_iteration_and_input(monkeypatch):
    monkeypatch.delenv("PRNG_SEED", raising=False)
    monkeypatch.delenv("PRNG_ITER", raising=False)
    text = Tactic.from_env(407001, 1).context(3, {"path": "a b"})
    assert "seed=407001" in text
    assert "iter=3" in text
    assert "PRNG_SEED=407001 PRNG_ITER=3" in text
    assert "'a b'" in text
