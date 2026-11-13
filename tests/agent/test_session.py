"""The model session: budgets, JSON answers with one retry, the trace."""

from __future__ import annotations

from typing import Any

import pytest

from masar.adapters.scripted import ScriptedModel
from masar.agent.session import Budget, BudgetExceeded, ModelOutputError, ModelSession, first_json_object
from masar.ports.model import Message, ModelUnavailable
from tests.support.clock import FakeClock

ASK = [Message("system", "rules"), Message("user", "data")]


def session(
    answers: list[Any], budget: Budget = Budget(), clock: FakeClock | None = None
) -> tuple[ModelSession, ScriptedModel]:
    model = ScriptedModel(answers)
    return ModelSession(model, clock or FakeClock(), "v-test", budget), model


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"a": 1}', {"a": 1}),
        ('Here you go:\n```json\n{"a": 1}\n```\nBye', {"a": 1}),
        ('I think {this} is it: {"a": {"b": [1, 2]}} and {"c": 3}', {"a": {"b": [1, 2]}}),
        ("no object here", None),
        ("[1, 2, 3]", None),
        ('{"a": ', None),
    ],
)
def test_the_first_json_object_is_found_wherever_it_starts(text: str, expected: dict[str, Any] | None) -> None:
    assert first_json_object(text) == expected


def test_a_json_answer_is_returned_and_traced() -> None:
    s, model = session(['{"ok": true}'])
    assert s.ask_json("extract", ASK) == {"ok": True}
    assert len(model.calls) == 1
    (step,) = s.steps
    assert (step.step, step.model, step.prompt_version, step.output) == (
        "extract",
        "scripted",
        "v-test",
        '{"ok": true}',
    )
    assert len(step.input_checksum) == 64
    assert s.tokens == step.tokens_in + step.tokens_out > 0


def test_the_trace_checksum_changes_with_the_input() -> None:
    s, _ = session(["a", "b", "c"])
    s.ask("x", ASK)
    s.ask("x", ASK)
    s.ask("x", [*ASK, Message("user", "more")])
    assert s.steps[0].input_checksum == s.steps[1].input_checksum != s.steps[2].input_checksum


def test_an_unreadable_answer_gets_one_more_try_with_the_reason() -> None:
    s, model = session(["sorry, I cannot", '{"ok": 1}'])
    assert s.ask_json("extract", ASK) == {"ok": 1}
    second = model.calls[1]
    assert [m.role for m in second] == ["system", "user", "assistant", "user"]
    assert second[2].content == "sorry, I cannot"
    assert "no JSON object" in second[3].content
    assert [step.step for step in s.steps] == ["extract", "extract:retry"]


def test_two_unreadable_answers_fail_the_step() -> None:
    s, model = session(["nope", "still nope", '{"late": 1}'])
    with pytest.raises(ModelOutputError, match="extract"):
        s.ask_json("extract", ASK)
    assert len(model.calls) == 2


def test_a_wrong_shape_is_retried_with_what_is_missing() -> None:
    def needs_items(value: dict[str, Any]) -> str | None:
        return None if "items" in value else 'needs "items"'

    s, model = session(['{"other": 1}', '{"items": []}'])
    assert s.ask_json("assess", ASK, needs_items) == {"items": []}
    assert 'needs "items"' in model.calls[1][3].content


def test_the_call_budget_stops_the_run() -> None:
    s, model = session(["a", "b", "c"], Budget(calls=2))
    s.ask("x", ASK)
    assert s.used_up() is None
    s.ask("x", ASK)
    assert s.used_up() == "calls"
    with pytest.raises(BudgetExceeded) as error:
        s.ask("x", ASK)
    assert error.value.limit == "calls"
    assert len(model.calls) == 2


def test_the_token_budget_stops_the_run() -> None:
    s, model = session(["x" * 400, "b"], Budget(tokens=100))
    s.ask("x", ASK)
    with pytest.raises(BudgetExceeded) as error:
        s.ask("x", ASK)
    assert error.value.limit == "tokens"
    assert len(model.calls) == 1


def test_tokens_sent_count_as_much_as_tokens_received() -> None:
    s, model = session(["ok", "b"], Budget(tokens=100))
    s.ask("x", [Message("user", "x" * 800)])
    assert s.tokens_in == 200
    with pytest.raises(BudgetExceeded) as error:
        s.ask("x", ASK)
    assert error.value.limit == "tokens"
    assert len(model.calls) == 1


def test_the_time_budget_stops_the_run() -> None:
    clock = FakeClock()
    s, model = session(["a", "b"], Budget(seconds=180), clock)
    clock.advance(179)
    s.ask("x", ASK)
    clock.advance(1)
    with pytest.raises(BudgetExceeded) as error:
        s.ask("x", ASK)
    assert error.value.limit == "time"
    assert len(model.calls) == 1


def test_the_output_limit_is_sent_with_every_call() -> None:
    seen: list[int] = []

    class Model(ScriptedModel):
        def complete(self, messages, max_output_tokens):  # type: ignore[no-untyped-def]
            seen.append(max_output_tokens)
            return super().complete(messages, max_output_tokens)

    ModelSession(Model(["a"]), FakeClock(), "v", Budget(output_tokens=777)).ask("x", ASK)
    assert seen == [777]


def test_the_duration_of_a_call_is_measured() -> None:
    clock = FakeClock()

    def slow(messages) -> str:  # type: ignore[no-untyped-def]
        clock.advance(1.5)
        return "done"

    s = ModelSession(ScriptedModel([slow]), clock, "v")
    s.ask("x", ASK)
    assert s.steps[0].duration_ms == 1500


def test_a_provider_failure_passes_through_and_leaves_no_step() -> None:
    s, _ = session([ModelUnavailable("HTTP 503")])
    with pytest.raises(ModelUnavailable, match="503"):
        s.ask("x", ASK)
    assert s.steps == []


def test_a_retry_that_the_budget_refuses_fails_as_budget() -> None:
    s, _ = session(["nope", '{"a": 1}'], Budget(calls=1))
    with pytest.raises(BudgetExceeded):
        s.ask_json("x", ASK)
