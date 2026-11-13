from __future__ import annotations

from datetime import date, timedelta

import pytest

from masar.domain.applications import (
    FINAL,
    Actor,
    ApplicationView,
    Attention,
    State,
    allowed_moves,
    move,
    needs_attention,
)

TODAY = date(2026, 11, 13)

PERSON_MOVES = {
    State.FOUND: {State.SHORTLISTED, State.SKIPPED},
    State.SHORTLISTED: {State.APPLIED, State.SKIPPED},
    State.DRAFTED: {State.APPLIED, State.SKIPPED},
    State.APPLIED: {State.INTERVIEWING, State.REJECTED, State.WITHDRAWN},
    State.INTERVIEWING: {State.OFFER, State.REJECTED, State.WITHDRAWN},
    State.SKIPPED: {State.FOUND},
    State.OFFER: set(),
    State.REJECTED: set(),
    State.WITHDRAWN: set(),
}


@pytest.mark.parametrize("current", list(State))
def test_every_move_of_the_person_is_allowed_or_refused_by_the_table(current: State) -> None:
    for target in State:
        result = move(current, target)

        assert result.ok == (target in PERSON_MOVES[current]), f"{current} -> {target}"
        assert allowed_moves(current) == PERSON_MOVES[current]


def test_masar_itself_can_only_mark_a_document_as_drafted() -> None:
    for current in State:
        expected = {State.DRAFTED} if current in (State.FOUND, State.SHORTLISTED) else set()

        assert allowed_moves(current, Actor.MASAR) == expected

    assert move(State.FOUND, State.DRAFTED, Actor.MASAR).unwrap() is State.DRAFTED
    assert not move(State.FOUND, State.APPLIED, Actor.MASAR).ok
    assert not move(State.APPLIED, State.DRAFTED, Actor.MASAR).ok


def test_a_refusal_says_what_is_possible() -> None:
    assert "shortlisted, skipped" in move(State.FOUND, State.OFFER).errors[0].message
    assert "final" in move(State.REJECTED, State.FOUND).errors[0].message
    assert "approve a document" in move(State.SHORTLISTED, State.DRAFTED).errors[0].message
    assert move(State.FOUND, State.FOUND).errors[0].code == "APPLICATION-MOVE"


def test_final_states() -> None:
    assert {State.OFFER, State.REJECTED, State.WITHDRAWN} == FINAL


def view(posting_id: int, state: State, days_ago: int, pending: int = 0, approved: int = 0) -> ApplicationView:
    return ApplicationView(posting_id, state, TODAY - timedelta(days=days_ago), pending, approved)


def test_what_needs_attention() -> None:
    items = needs_attention(
        [
            view(1, State.FOUND, 30),
            view(2, State.SHORTLISTED, 3),
            view(3, State.SHORTLISTED, 1, pending=1),
            view(4, State.SHORTLISTED, 1, approved=1),
            view(5, State.APPLIED, 9),
            view(6, State.APPLIED, 10),
            view(7, State.APPLIED, 25),
            view(8, State.INTERVIEWING, 6),
            view(9, State.INTERVIEWING, 7),
            view(10, State.REJECTED, 100, pending=1),
            view(11, State.SKIPPED, 2, pending=1),
            view(12, State.DRAFTED, 2, pending=1, approved=1),
        ],
        TODAY,
    )

    assert [(i.posting_id, i.reason) for i in items] == [
        (12, Attention.DRAFT_WAITING),
        (3, Attention.DRAFT_WAITING),
        (2, Attention.NO_DRAFT),
        (7, Attention.APPLIED_QUIET),
        (6, Attention.APPLIED_QUIET),
        (9, Attention.INTERVIEW_QUIET),
    ]
    assert items[3].days == 25


def test_nothing_needs_attention_when_nothing_is_open() -> None:
    assert needs_attention([], TODAY) == []
    assert needs_attention([view(1, State.OFFER, 50), view(2, State.FOUND, 1)], TODAY) == []
