"""The two model clients: what they send, what they read, and what they say when it goes wrong."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from masar.adapters.llm import AnthropicModel, OpenAICompatibleModel, build_model
from masar.adapters.settings import Settings, SettingsError
from masar.ports.model import Message, ModelUnavailable

KEY = "sk-test-SECRET-123"
MESSAGES = [Message("system", "rules"), Message("user", "data"), Message("assistant", "bad"), Message("user", "again")]


def client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def openai(
    handler: Callable[[httpx.Request], httpx.Response], base: str = "https://api.openai.com/v1"
) -> OpenAICompatibleModel:
    return OpenAICompatibleModel("gpt-test", KEY, base, client(handler))


def anthropic(handler: Callable[[httpx.Request], httpx.Response]) -> AnthropicModel:
    return AnthropicModel("claude-test", KEY, "https://api.anthropic.com", client(handler))


OPENAI_OK = {
    "model": "gpt-test-2026-01",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": '{"ok": true}'}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 120, "completion_tokens": 8, "total_tokens": 128},
}
ANTHROPIC_OK = {
    "model": "claude-test-2026",
    "content": [
        {"type": "thinking", "thinking": "hmm"},
        {"type": "text", "text": '{"ok": '},
        {"type": "text", "text": "true}"},
    ],
    "usage": {"input_tokens": 99, "output_tokens": 7},
}


class TestOpenAICompatible:
    def test_the_request_and_the_answer(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=OPENAI_OK)

        result = openai(handler).complete(MESSAGES, 2000)

        (request,) = seen
        assert str(request.url) == "https://api.openai.com/v1/chat/completions"
        assert request.headers["authorization"] == f"Bearer {KEY}"
        assert json.loads(request.content) == {
            "model": "gpt-test",
            "messages": [
                {"role": "system", "content": "rules"},
                {"role": "user", "content": "data"},
                {"role": "assistant", "content": "bad"},
                {"role": "user", "content": "again"},
            ],
            "max_tokens": 2000,
            "temperature": 0,
        }
        assert (result.text, result.tokens_in, result.tokens_out, result.model) == (
            '{"ok": true}',
            120,
            8,
            "gpt-test-2026-01",
        )

    def test_another_server_is_reached_at_its_own_address(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, json=OPENAI_OK)

        openai(handler, "http://localhost:11434/v1/").complete(MESSAGES, 10)
        assert seen == ["http://localhost:11434/v1/chat/completions"]

    def test_a_model_that_wants_the_other_limit_name_gets_one_more_try(self) -> None:
        bodies: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            if len(bodies) == 1:
                message = "Unsupported parameter: 'max_tokens'. Use 'max_completion_tokens' instead."
                return httpx.Response(400, json={"error": {"message": message}})
            return httpx.Response(200, json=OPENAI_OK)

        result = openai(handler).complete(MESSAGES, 2000)

        assert result.text == '{"ok": true}'
        assert "max_tokens" in bodies[0]
        assert bodies[1]["max_completion_tokens"] == 2000
        assert "max_tokens" not in bodies[1]
        assert "temperature" not in bodies[1]

    def test_missing_usage_counts_as_zero_and_the_asked_model_is_named(self) -> None:
        body = {"choices": [{"message": {"content": "hi"}}]}
        result = openai(lambda request: httpx.Response(200, json=body)).complete(MESSAGES, 10)
        assert (result.tokens_in, result.tokens_out, result.model) == (0, 0, "gpt-test")

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"choices": []},
            {"choices": [{"message": {"content": None}}]},
            {"choices": [{"message": {"content": "  "}}]},
            {"choices": "x"},
        ],
    )
    def test_an_answer_with_no_text_is_a_failure(self, body: dict[str, Any]) -> None:
        with pytest.raises(ModelUnavailable, match="gave no text"):
            openai(lambda request: httpx.Response(200, json=body)).complete(MESSAGES, 10)


class TestAnthropic:
    def test_the_request_and_the_answer(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=ANTHROPIC_OK)

        result = anthropic(handler).complete(MESSAGES, 2000)

        (request,) = seen
        assert str(request.url) == "https://api.anthropic.com/v1/messages"
        assert request.headers["x-api-key"] == KEY
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert "authorization" not in request.headers
        assert json.loads(request.content) == {
            "model": "claude-test",
            "system": "rules",
            "messages": [
                {"role": "user", "content": "data"},
                {"role": "assistant", "content": "bad"},
                {"role": "user", "content": "again"},
            ],
            "max_tokens": 2000,
            "temperature": 0,
        }
        # Only the text parts make the answer.
        assert (result.text, result.tokens_in, result.tokens_out, result.model) == (
            '{"ok": true}',
            99,
            7,
            "claude-test-2026",
        )

    def test_parts_of_another_type_are_not_the_answer(self) -> None:
        body = {
            "content": [
                {"type": "tool_use", "text": "not for the reader"},
                {"type": "text", "text": "the answer"},
                "odd",
            ]
        }
        result = anthropic(lambda request: httpx.Response(200, json=body)).complete(MESSAGES, 10)
        assert result.text == "the answer"

    @pytest.mark.parametrize(
        "body", [{}, {"content": []}, {"content": [{"type": "thinking", "thinking": "x"}]}, {"content": "text"}]
    )
    def test_an_answer_with_no_text_is_a_failure(self, body: dict[str, Any]) -> None:
        with pytest.raises(ModelUnavailable, match="Anthropic gave no text"):
            anthropic(lambda request: httpx.Response(200, json=body)).complete(MESSAGES, 10)


@pytest.mark.parametrize("make", [openai, anthropic])
class TestFailures:
    def test_an_http_error_names_the_status_and_never_the_key(self, make: Callable[..., Any]) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": {"message": f"Incorrect API key provided: {KEY}"}})

        with pytest.raises(ModelUnavailable) as error:
            make(handler).complete(MESSAGES, 10)
        assert "HTTP 401" in str(error.value)
        assert KEY not in str(error.value)
        assert "***" in str(error.value)

    def test_a_long_error_body_is_cut(self, make: Callable[..., Any]) -> None:
        with pytest.raises(ModelUnavailable) as error:
            make(lambda request: httpx.Response(500, text="x" * 5000)).complete(MESSAGES, 10)
        assert len(str(error.value)) < 300

    def test_a_timeout(self, make: Callable[..., Any]) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow", request=request)

        with pytest.raises(ModelUnavailable, match="did not answer in time"):
            make(handler).complete(MESSAGES, 10)

    def test_a_network_failure_names_no_address_and_no_key(self, make: Callable[..., Any]) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(f"cannot connect with {KEY}", request=request)

        with pytest.raises(ModelUnavailable) as error:
            make(handler).complete(MESSAGES, 10)
        assert "could not be reached (ConnectError)" in str(error.value)
        assert KEY not in str(error.value)
        assert error.value.__cause__ is None  # the original error, which may hold more, is not chained

    def test_a_success_that_is_not_json(self, make: Callable[..., Any]) -> None:
        with pytest.raises(ModelUnavailable, match="not JSON"):
            make(lambda request: httpx.Response(200, text="<html>gateway</html>")).complete(MESSAGES, 10)


class TestBuild:
    def settings(self, **changes: Any) -> Settings:
        return Settings(Path("/tmp/x"), **{"provider": "openai", "model": "m", "api_key": KEY, **changes})

    def test_the_provider_picks_the_client(self) -> None:
        assert isinstance(build_model(self.settings()), OpenAICompatibleModel)
        assert isinstance(build_model(self.settings(provider="anthropic")), AnthropicModel)
        assert build_model(self.settings()).name == "m"

    def test_the_base_url_setting_is_used(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, json=OPENAI_OK)

        build_model(self.settings(base_url="https://proxy.test/v1"), client(handler)).complete(MESSAGES, 5)
        assert seen == ["https://proxy.test/v1/chat/completions"]

    def test_no_model_configured_says_what_to_set(self) -> None:
        with pytest.raises(SettingsError, match="MASAR_LLM_PROVIDER"):
            build_model(Settings(Path("/tmp/x")))
