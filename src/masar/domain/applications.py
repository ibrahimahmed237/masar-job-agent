"""An application's life: which moves are allowed, who may make them, and what needs attention today."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from masar.domain.findings import Finding, Result


class State(StrEnum):
    FOUND = "found"
    SHORTLISTED = "shortlisted"
    DRAFTED = "drafted"
    APPLIED = "applied"
    INTERVIEWING = "interviewing"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    SKIPPED = "skipped"


class Actor(StrEnum):
    PERSON = "person"
    MASAR = "masar"


_MOVES: dict[State, frozenset[State]] = {
    State.FOUND: frozenset({State.SHORTLISTED, State.DRAFTED, State.SKIPPED}),
    State.SHORTLISTED: frozenset({State.DRAFTED, State.APPLIED, State.SKIPPED}),
    State.DRAFTED: frozenset({State.APPLIED, State.SKIPPED}),
    State.APPLIED: frozenset({State.INTERVIEWING, State.REJECTED, State.WITHDRAWN}),
    State.INTERVIEWING: frozenset({State.OFFER, State.REJECTED, State.WITHDRAWN}),
    State.SKIPPED: frozenset({State.FOUND}),
    State.OFFER: frozenset(),
    State.REJECTED: frozenset(),
    State.WITHDRAWN: frozenset(),
}

FINAL = frozenset(state for state, moves in _MOVES.items() if not moves)

APPLIED_QUIET_DAYS = 10
INTERVIEW_QUIET_DAYS = 7


def allowed_moves(state: State, actor: Actor = Actor.PERSON) -> frozenset[State]:
    """Where an application may go from a state. Masar itself may only mark a document as drafted."""
    moves = _MOVES[state]
    if actor is Actor.MASAR:
        return moves & {State.DRAFTED}
    return moves - {State.DRAFTED}


def move(current: State, target: State, actor: Actor = Actor.PERSON) -> Result[State]:
    """The new state, or why the move is refused."""
    allowed = allowed_moves(current, actor)
    if target in allowed:
        return Result(target)
    if current in FINAL:
        reason = f"'{current}' is final"
    elif target is State.DRAFTED and actor is Actor.PERSON:
        reason = "'drafted' is set by Masar when you approve a document"
    else:
        options = ", ".join(sorted(allowed)) or "nothing"
        reason = f"from '{current}' you can move to: {options}"
    return Result(None, (Finding.error("APPLICATION-MOVE", "state", reason),))


class Attention(StrEnum):
    DRAFT_WAITING = "draft-waiting"
    NO_DRAFT = "no-draft"
    APPLIED_QUIET = "applied-quiet"
    INTERVIEW_QUIET = "interview-quiet"


@dataclass(frozen=True, slots=True)
class ApplicationView:
    """What ``needs_attention`` must know about one application."""

    posting_id: int
    state: State
    last_event: date
    pending_drafts: int = 0
    approved_documents: int = 0


@dataclass(frozen=True, slots=True)
class AttentionItem:
    posting_id: int
    reason: Attention
    days: int


def needs_attention(applications: list[ApplicationView], today: date) -> list[AttentionItem]:
    """What the person should look at today, most urgent first within each reason."""
    items: list[AttentionItem] = []
    for a in applications:
        quiet = (today - a.last_event).days
        if a.pending_drafts and a.state not in FINAL and a.state is not State.SKIPPED:
            items.append(AttentionItem(a.posting_id, Attention.DRAFT_WAITING, quiet))
        if a.state is State.SHORTLISTED and not a.pending_drafts and not a.approved_documents:
            items.append(AttentionItem(a.posting_id, Attention.NO_DRAFT, quiet))
        if a.state is State.APPLIED and quiet >= APPLIED_QUIET_DAYS:
            items.append(AttentionItem(a.posting_id, Attention.APPLIED_QUIET, quiet))
        if a.state is State.INTERVIEWING and quiet >= INTERVIEW_QUIET_DAYS:
            items.append(AttentionItem(a.posting_id, Attention.INTERVIEW_QUIET, quiet))
    order = list(Attention)
    return sorted(items, key=lambda i: (order.index(i.reason), -i.days, i.posting_id))
