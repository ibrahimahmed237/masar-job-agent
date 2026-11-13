"""A model that answers from a script. For tests, for the demo, and for proving the scoring of the evaluations."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from masar.ports.model import ChatResult, Message, ModelUnavailable

Answer = str | dict[str, Any] | Exception | Callable[[Sequence[Message]], str]


class ScriptedModel:
    """Returns its prepared answers in order and keeps what it was asked."""

    def __init__(self, answers: Sequence[Answer], name: str = "scripted") -> None:
        self._answers = list(answers)
        self._name = name
        self.calls: list[list[Message]] = []

    @property
    def name(self) -> str:
        return self._name

    def complete(self, messages: Sequence[Message], max_output_tokens: int) -> ChatResult:
        self.calls.append(list(messages))
        if not self._answers:
            raise ModelUnavailable("the script has no answer left")
        answer = self._answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        if callable(answer):
            text = answer(messages)
        elif isinstance(answer, dict):
            text = json.dumps(answer, ensure_ascii=False)
        else:
            text = answer
        # A rough count, four characters to a token, so that budgets can be tested.
        tokens_in = sum(len(m.content) for m in messages) // 4
        return ChatResult(text=text, tokens_in=tokens_in, tokens_out=len(text) // 4, model=self._name)

    @property
    def prompts(self) -> str:
        """Everything this model was sent, as one text."""
        return "\n".join(m.content for call in self.calls for m in call)
