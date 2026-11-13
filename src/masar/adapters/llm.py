"""Model providers over plain HTTP (ADR-0010): any OpenAI-compatible server, and Anthropic."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from masar.adapters.settings import Settings, SettingsError
from masar.ports.model import ChatModel, ChatResult, Message, ModelUnavailable

TIMEOUT_SECONDS = 60.0
OPENAI_URL = "https://api.openai.com/v1"
ANTHROPIC_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


class _HttpModel:
    provider = "model"

    def __init__(self, model: str, api_key: str, base_url: str, client: httpx.Client | None = None) -> None:
        self._model = model
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS)

    @property
    def name(self) -> str:
        return self._model

    def _safe(self, text: str) -> str:
        """A provider's words, short, and without the key if it ever echoes it."""
        return " ".join(text.replace(self._key, "***").split())[:200]

    def _post(self, path: str, headers: dict[str, str], body: dict[str, Any]) -> httpx.Response:
        try:
            return self._client.post(f"{self._base}{path}", headers=headers, json=body)
        except httpx.TimeoutException:
            raise ModelUnavailable(f"{self.provider} did not answer in time") from None
        except httpx.HTTPError as error:
            raise ModelUnavailable(f"{self.provider} could not be reached ({type(error).__name__})") from None

    def _json(self, answer: httpx.Response) -> dict[str, Any]:
        if answer.status_code // 100 != 2:
            raise ModelUnavailable(f"{self.provider} answered HTTP {answer.status_code}: {self._safe(answer.text)}")
        try:
            data = answer.json()
        except ValueError:
            data = None
        if not isinstance(data, dict):
            raise ModelUnavailable(f"{self.provider} gave an answer that is not JSON")
        return data


class OpenAICompatibleModel(_HttpModel):
    """Chat completions, as OpenAI and many other servers offer them."""

    provider = "the model server"

    def complete(self, messages: Sequence[Message], max_output_tokens: int) -> ChatResult:
        headers = {"Authorization": f"Bearer {self._key}"}
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": max_output_tokens,
            "temperature": 0,
        }
        answer = self._post("/chat/completions", headers, body)
        if answer.status_code == 400 and "max_completion_tokens" in answer.text:
            # Some models take the limit under another name and no temperature. One more try, their way.
            del body["max_tokens"], body["temperature"]
            body["max_completion_tokens"] = max_output_tokens
            answer = self._post("/chat/completions", headers, body)
        data = self._json(answer)
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            text = None
        if not isinstance(text, str) or not text.strip():
            raise ModelUnavailable(f"{self.provider} gave no text")
        usage = _dict(data.get("usage"))
        return ChatResult(
            text=text,
            tokens_in=_int(usage.get("prompt_tokens")),
            tokens_out=_int(usage.get("completion_tokens")),
            model=data["model"] if isinstance(data.get("model"), str) else self._model,
        )


class AnthropicModel(_HttpModel):
    provider = "Anthropic"

    def complete(self, messages: Sequence[Message], max_output_tokens: int) -> ChatResult:
        body = {
            "model": self._model,
            "system": "\n\n".join(m.content for m in messages if m.role == "system"),
            "messages": [{"role": m.role, "content": m.content} for m in messages if m.role != "system"],
            "max_tokens": max_output_tokens,
            "temperature": 0,
        }
        headers = {"x-api-key": self._key, "anthropic-version": ANTHROPIC_VERSION}
        data = self._json(self._post("/v1/messages", headers, body))
        content = data.get("content")
        parts: list[Any] = content if isinstance(content, list) else []
        text = "".join(
            part["text"]
            for part in parts
            if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str)
        )
        if not text.strip():
            raise ModelUnavailable(f"{self.provider} gave no text")
        usage = _dict(data.get("usage"))
        return ChatResult(
            text=text,
            tokens_in=_int(usage.get("input_tokens")),
            tokens_out=_int(usage.get("output_tokens")),
            model=data["model"] if isinstance(data.get("model"), str) else self._model,
        )


def build_model(settings: Settings, client: httpx.Client | None = None) -> ChatModel:
    """The model the settings name. Raises ``SettingsError`` when none is configured."""
    if settings.provider is None or settings.model is None or settings.api_key is None:
        raise SettingsError(
            "no model is configured: set MASAR_LLM_PROVIDER (openai or anthropic), MASAR_LLM_MODEL"
            " and MASAR_LLM_API_KEY"
        )
    if settings.provider == "anthropic":
        return AnthropicModel(settings.model, settings.api_key, settings.base_url or ANTHROPIC_URL, client)
    return OpenAICompatibleModel(settings.model, settings.api_key, settings.base_url or OPENAI_URL, client)
