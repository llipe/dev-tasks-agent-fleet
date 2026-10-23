"""
Drive ``bedrock_adapter.review`` against the fake Converse (S-210).

Builds a first prompt from the S-209 input factories, injects a deterministic
nonce factory, a recording ``warn`` and sink, and a fake clock, so the adapter
tests and the RT-11 property tactic share one harness.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from budget import ContextInputs
from config import Settings
from prompt import Prompt, build_prompt
from tests.helpers.prompt_inputs import NONCE, diff_ctx, file_diff, inputs

OPENAI_ID = "us.openai.gpt-5-6-sol-v1:0"
DEEPSEEK_ID = "us.deepseek.v4-pro-v1:0"
BUDGET = 30_000
FILES = ("src/app.py", "src/util.py")


def settings(
    model_id: str = OPENAI_ID,
    price_in: float | None = None,
    price_out: float | None = None,
) -> Settings:
    return Settings(
        supabase_url="https://supabase.example",
        supabase_key_secret_id="secret-id",
        model_id=model_id,
        panel_base_url="https://panel.example",
        price_input_per_mtok=price_in,
        price_output_per_mtok=price_out,
    )


def review_inputs(
    files: Sequence[str] = FILES, *, head: str = "x = 1\n", **kw: Any
) -> ContextInputs:
    diff = diff_ctx([file_diff(f, head=head) for f in files]) if files else None
    if diff is None:
        diff = diff_ctx([file_diff("src/app.py", head=None, status="removed")])
    return inputs(diff=diff, **kw)


def first_prompt(ins: ContextInputs, budget: int = BUDGET, nonce: str = NONCE) -> Prompt:
    p = build_prompt(ins, max_context_tokens=budget, max_diff_lines=2000, nonce=nonce)
    assert isinstance(p, Prompt)
    return p


def counter_nonces(start: int = 1) -> Callable[[], str]:
    counter = itertools.count(start)
    return lambda: f"{next(counter):016x}"


@dataclass
class Recorder:
    """Records ``warn(message, **data)`` calls and the prompts the sink receives."""

    warns: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    prompts: list[Prompt] = field(default_factory=list)

    def warn(self, message: str, **data: Any) -> None:
        self.warns.append((message, data))

    def sink(self, p: Prompt) -> None:
        self.prompts.append(p)

    @property
    def messages(self) -> list[str]:
        return [m for m, _ in self.warns]


class Clock:
    """A monotonic clock that advances ``step`` seconds per reading."""

    def __init__(self, step: float = 0.5, start: float = 100.0) -> None:
        self.now = start
        self.step = step

    def __call__(self) -> float:
        value = self.now
        self.now += self.step
        return value


def run(
    fake: Any,
    ins: ContextInputs | None = None,
    *,
    prompt: Prompt | None = None,
    model_id: str = OPENAI_ID,
    effort: str = "high",
    price_in: float | None = None,
    price_out: float | None = None,
    recorder: Recorder | None = None,
    budget: int = BUDGET,
    clock: Callable[[], float] | None = None,
    deadline: float | None = None,
    nonce_factory: Callable[[], str] | None = None,
) -> Any:
    import bedrock_adapter

    ins = ins if ins is not None else review_inputs()
    p = prompt if prompt is not None else first_prompt(ins, budget)
    rec = recorder if recorder is not None else Recorder()
    return bedrock_adapter.review(
        p,
        ins,
        client=fake,
        settings=settings(model_id, price_in, price_out),
        reasoning_effort=effort,
        max_diff_lines=2000,
        warn=rec.warn,
        sink=rec.sink,
        nonce_factory=nonce_factory or counter_nonces(),
        clock=clock or Clock(),
        deadline=deadline,
    )
