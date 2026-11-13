"""Every model call of a run goes through one session: budgets, JSON answers, and a trace."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, cast

from masar.ports.clock import Clock
from masar.ports.model import ChatModel, Message


class BudgetExceeded(Exception):
    """A run asked for more calls, tokens or time than it may use."""

    def __init__(self, limit: str) -> None:
        super().__init__(f"the run used up its {limit}")
        self.limit = limit


class ModelOutputError(Exception):
    """The model's answer could not be read, also after one more try."""


@dataclass(frozen=True, slots=True)
class Budget:
    """What one run may spend."""

    calls: int = 12
    tokens: int = 60_000
    seconds: float = 180.0
    output_tokens: int = 2_000


@dataclass(frozen=True, slots=True)
class Step:
    """One model call, as kept in the trace. The input is kept as a checksum only."""

    step: str
    model: str
    prompt_version: str
    tokens_in: int
    tokens_out: int
    duration_ms: int
    input_checksum: str
    output: str


Validate = Callable[[dict[str, Any]], str | None]


class ModelSession:
    def __init__(self, model: ChatModel, clock: Clock, prompt_version: str, budget: Budget = Budget()) -> None:
        self._model = model
        self._clock = clock
        self._prompt_version = prompt_version
        self._budget = budget
        self._started = clock.monotonic()
        self.steps: list[Step] = []

    @property
    def tokens_in(self) -> int:
        return sum(step.tokens_in for step in self.steps)

    @property
    def tokens_out(self) -> int:
        return sum(step.tokens_out for step in self.steps)

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out

    def used_up(self) -> str | None:
        """The limit that is reached, or None while the run may still call the model."""
        if len(self.steps) >= self._budget.calls:
            return "calls"
        if self.tokens >= self._budget.tokens:
            return "tokens"
        if self._clock.monotonic() - self._started >= self._budget.seconds:
            return "time"
        return None

    def ask(self, step: str, messages: Sequence[Message]) -> str:
        """One answer as text. Raises ``BudgetExceeded`` before calling, ``ModelUnavailable`` from the provider."""
        if limit := self.used_up():
            raise BudgetExceeded(limit)
        before = self._clock.monotonic()
        result = self._model.complete(messages, self._budget.output_tokens)
        took = self._clock.monotonic() - before
        content = "\x1e".join(f"{m.role}\x1f{m.content}" for m in messages)
        self.steps.append(
            Step(
                step=step,
                model=result.model,
                prompt_version=self._prompt_version,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                duration_ms=round(took * 1000),
                input_checksum=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                output=result.text,
            )
        )
        return result.text

    def ask_json(self, step: str, messages: Sequence[Message], validate: Validate | None = None) -> dict[str, Any]:
        """One answer as a JSON object. An answer that cannot be read gets one more try, with the reason."""
        answer = self.ask(step, messages)
        value, problem = _read(answer, validate)
        if value is not None:
            return value
        again = [
            *messages,
            Message("assistant", answer),
            Message("user", f"That answer could not be used: {problem}. Answer again with only the JSON object."),
        ]
        answer = self.ask(f"{step}:retry", again)
        value, problem = _read(answer, validate)
        if value is None:
            raise ModelOutputError(f"{step}: {problem}")
        return value


def _read(answer: str, validate: Validate | None) -> tuple[dict[str, Any] | None, str]:
    value = first_json_object(answer)
    if value is None:
        return None, "it holds no JSON object"
    problem = validate(value) if validate else None
    return (None, problem) if problem else (value, "")


def first_json_object(text: str) -> dict[str, Any] | None:
    """The first JSON object in a text, wherever it starts: in a code fence, after a sentence."""
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            value, _ = decoder.raw_decode(text, start)
        except ValueError:
            start = text.find("{", start + 1)
        else:
            return cast(dict[str, Any], value)  # a JSON value that starts with "{" is an object
    return None
