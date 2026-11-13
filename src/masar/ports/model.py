"""The one thing Masar asks of a language model: messages in, text out (ADR-0010)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class ChatResult:
    text: str
    tokens_in: int
    tokens_out: int
    model: str


class ModelUnavailable(Exception):
    """The provider could not be reached, or did not give an answer. The message never holds a key."""


class ChatModel(Protocol):
    @property
    def name(self) -> str: ...

    def complete(self, messages: Sequence[Message], max_output_tokens: int) -> ChatResult:
        """One answer for the messages. Raises ``ModelUnavailable``."""
        ...
