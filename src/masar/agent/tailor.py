"""The tailor flow: a draft is written, checked, repaired, judged, assembled, and then waits for the person.

The flow pauses at ``approval`` and is kept in the checkpointer under its run id. Another process can build the
same graph on the same database and go on from there. Nothing leaves the flow as "approved" unless a person said so.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from masar.agent.facts import facts_for_draft
from masar.agent.prompts import draft_messages, judge_messages, repair_messages
from masar.agent.session import BudgetExceeded, ModelOutputError, ModelSession
from masar.domain import codec
from masar.domain.career import Career
from masar.domain.claims import (
    Block,
    ClaimContext,
    DocumentKind,
    Violation,
    check_document,
    parse_blocks,
)
from masar.domain.document import Document, assemble
from masar.domain.job import Job

MAX_REPAIRS = 2
RECURSION_LIMIT = 25

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
FAILED = "failed"


class TailorState(TypedDict, total=False):
    # Given at the start.
    kind: str
    language: str
    job: dict[str, Any]
    assessment: list[dict[str, Any]] | None
    posting_text: str
    # Added by the flow.
    fact_ids: list[str]
    blocks: list[dict[str, Any]]
    violations: list[dict[str, Any]]
    judgements: dict[str, dict[str, Any]]
    judged: bool
    degraded: str | None
    tries: int
    document: dict[str, Any] | None
    warnings: list[str]
    status: str
    reason: str | None
    edited: bool
    decision: dict[str, Any] | None
    problem: str | None


@dataclass(frozen=True)
class TailorDeps:
    """What the flow works with. Given when the graph is built: the career file is always the current one."""

    session: ModelSession
    career: Career
    today: date


@dataclass(frozen=True)
class TailorOutcome:
    status: str
    document: Document | None
    warnings: tuple[str, ...]
    judged: bool
    edited: bool
    reason: str | None  # why a run failed
    problem: str | None  # why the last decision was not taken


class NotPaused(Exception):
    """The run is not waiting for a decision: it never started, it failed, or it was decided already."""


def _key(block: Block) -> str:
    """A block's identity for the judge: the same words on the same facts are judged once."""
    return "\x1f".join((block.section.value, block.kind.value, block.text, *sorted(block.facts)))


def _blocks_given(value: dict[str, Any]) -> str | None:
    result = parse_blocks(value)
    return None if result.ok else "; ".join(f"{f.path}: {f.message}" for f in result.errors)


def _list_given(name: str) -> Any:
    def check(value: dict[str, Any]) -> str | None:
        return None if isinstance(value.get(name), list) else f'the object needs a "{name}" list'

    return check


def build_tailor_graph(deps: TailorDeps, checkpointer: Any) -> Any:
    career = deps.career
    facts_by_id = {fact.id: fact for fact in career.facts}

    def kind_of(state: TailorState) -> DocumentKind:
        return DocumentKind(state["kind"])

    def job_of(state: TailorState) -> Job:
        return codec.job_from_data(state["job"])

    def context(state: TailorState) -> ClaimContext:
        return ClaimContext(
            career=career,
            today=deps.today,
            language=state["language"],
            job=job_of(state),
            posting_text=state.get("posting_text", ""),
        )

    def planned(state: TailorState) -> list[Any]:
        return [facts_by_id[fact_id] for fact_id in state.get("fact_ids", []) if fact_id in facts_by_id]

    def plan(state: TailorState) -> TailorState:
        data = state.get("assessment")
        assessment = codec.assessment_from_data(data) if data is not None else None
        facts = facts_for_draft(career, job_of(state), assessment, deps.today)
        return {"fact_ids": [fact.id for fact in facts], "tries": 0, "edited": False}

    def draft(state: TailorState) -> TailorState:
        data = state.get("assessment")
        ctx = context(state)
        messages = draft_messages(
            kind_of(state),
            state["language"],
            job_of(state),
            codec.assessment_from_data(data) if data is not None else None,
            planned(state),
            metrics=career.style.metrics,
            years=ctx.years,
        )
        raw = deps.session.ask_json("draft", messages, _blocks_given)
        return {"blocks": codec.blocks_to_data(parse_blocks(raw).unwrap())}

    def check(state: TailorState) -> TailorState:
        blocks = codec.blocks_from_data(state["blocks"])
        return {"violations": codec.violations_to_data(check_document(kind_of(state), blocks, context(state)))}

    def judge(state: TailorState) -> TailorState:
        blocks = codec.blocks_from_data(state["blocks"])
        violations = codec.violations_from_data(state["violations"])
        failed_code = {v.block for v in violations}
        judgements = dict(state.get("judgements", {}))
        degraded = state.get("degraded")
        # Only what code let through is worth a model's opinion. A plain block is judged too: it must say
        # nothing about the person, and code cannot see a claim that names no skill, number or employer.
        passed = [i for i in range(len(blocks)) if i not in failed_code]
        todo = [i for i in passed if _key(blocks[i]) not in judgements]
        if todo and not degraded:
            try:
                raw = deps.session.ask_json("judge", judge_messages(blocks, todo, facts_by_id), _list_given("verdicts"))
            except BudgetExceeded as error:
                degraded = f"not judged: {error}"
            except ModelOutputError:
                degraded = "not judged: the reviewing model gave no answer that could be read"
            else:
                for entry in raw["verdicts"]:
                    if not isinstance(entry, Mapping):
                        continue
                    index, supported, reason = entry.get("block"), entry.get("supported"), entry.get("reason")
                    # A verdict counts only for a block that was asked about, and only as a plain yes or no.
                    if type(index) is int and index in todo and isinstance(supported, bool):
                        judgements[_key(blocks[index])] = {
                            "supported": supported,
                            "reason": " ".join(reason.split())[:200] if isinstance(reason, str) else "",
                        }
        for i in passed:
            verdict = judgements.get(_key(blocks[i]))
            if verdict is not None and verdict["supported"] is False:
                violations.append(Violation("NOT_SUPPORTED", i, verdict["reason"] or "it says more than its facts"))
        return {
            "judgements": judgements,
            "violations": codec.violations_to_data(violations),
            "judged": all(_key(blocks[i]) in judgements for i in passed),
            "degraded": degraded,
        }

    def repair(state: TailorState) -> TailorState:
        blocks = list(codec.blocks_from_data(state["blocks"]))
        violations = codec.violations_from_data(state["violations"])
        tries = state.get("tries", 0) + 1
        ctx = context(state)
        messages = repair_messages(
            blocks, violations, planned(state), state["language"], metrics=career.style.metrics, years=ctx.years
        )
        try:
            raw = deps.session.ask_json("repair", messages, _list_given("repairs"))
        except BudgetExceeded as error:
            # The checks run once more on what there is; the judge is not asked again.
            return {"tries": tries, "degraded": f"repair stopped: {error}"}
        except ModelOutputError:
            return {"tries": tries, "degraded": "repair stopped: the model gave no answer that could be read"}
        failing = {v.block for v in violations}
        new: dict[int, Block | None] = {}
        for entry in raw["repairs"]:
            if not isinstance(entry, Mapping):
                continue
            index, text = entry.get("block"), entry.get("text")
            # A repair may only touch a block that failed, and only once.
            if type(index) is not int or index not in failing or index in new or not isinstance(text, str):
                continue
            if not text.strip():
                new[index] = None
                continue
            old = blocks[index]
            cited = entry.get("facts")
            # The section and the kind stay: a claim cannot be repaired into a block that is checked less.
            again = parse_blocks(
                [
                    {
                        "section": old.section.value,
                        "kind": old.kind.value,
                        "text": text,
                        "facts": cited if isinstance(cited, list) else list(old.facts),
                        "fact": old.fact,
                    }
                ]
            )
            if again.value:
                new[index] = again.value[0]
        repaired = [new.get(i, block) for i, block in enumerate(blocks)]
        return {"blocks": codec.blocks_to_data(block for block in repaired if block is not None), "tries": tries}

    def build(state: TailorState) -> TailorState:
        blocks = codec.blocks_from_data(state["blocks"])
        violations = codec.violations_from_data(state["violations"])
        result = assemble(kind_of(state), state["language"], blocks, violations, career, job_of(state))
        if result.value is None:
            reason = "; ".join(finding.message for finding in result.errors)
            return {"status": FAILED, "reason": reason, "document": None}
        degraded = state.get("degraded")
        warnings = [degraded] if degraded else []
        if not state.get("judged", False) and not warnings:
            warnings.append("not judged: the reviewing model gave no verdict for some blocks")
        return {"status": PENDING, "document": codec.document_to_data(result.value), "warnings": warnings}

    def approval(state: TailorState) -> TailorState:
        # Nothing may happen before the pause: on resume this node runs again from its first line.
        decision = interrupt({"status": PENDING})
        return {"decision": dict(decision) if isinstance(decision, Mapping) else {"action": None}}

    def decide(state: TailorState) -> TailorState:
        decision = state.get("decision") or {}
        action = decision.get("action")
        kind = kind_of(state)
        if action == "reject":
            return {"status": REJECTED, "problem": None}
        if action == "approve":
            # The career file may have changed since the draft. What is approved must be true today.
            document = codec.document_from_data(state["document"] or {})
            violations = check_document(kind, document.blocks, context(state))
            if violations:
                listed = "; ".join(f"{v.code}: {v.detail}" for v in violations[:5])
                return {"problem": f"not approved: the draft no longer passes the checks ({listed})"}
            return {"status": APPROVED, "problem": None}
        if action == "edit":
            parsed = parse_blocks(decision.get("blocks"))
            if parsed.value is None:
                return {"problem": "edit refused: " + "; ".join(f.message for f in parsed.errors)}
            violations = check_document(kind, parsed.value, context(state))
            result = assemble(kind, state["language"], parsed.value, violations, career, job_of(state))
            if result.value is None:
                return {"problem": "edit refused: " + "; ".join(f.message for f in result.errors)}
            return {
                "blocks": codec.blocks_to_data(parsed.value),
                "violations": codec.violations_to_data(violations),
                "document": codec.document_to_data(result.value),
                "warnings": ["edited by hand: checked by code, not judged by a model"],
                "judged": False,
                "edited": True,
                "problem": None,
            }
        return {"problem": f"unknown decision: {action!r}"}

    def after_judge(state: TailorState) -> str:
        again = state["violations"] and state.get("tries", 0) < MAX_REPAIRS and not state.get("degraded")
        return "repair" if again else "assemble"

    def after_assemble(state: TailorState) -> str:
        return END if state.get("status") == FAILED else "approval"

    def after_decide(state: TailorState) -> str:
        return END if state.get("status") in (APPROVED, REJECTED) else "approval"

    graph = StateGraph(TailorState)
    graph.add_node("plan", plan)
    graph.add_node("draft", draft)
    graph.add_node("check", check)
    graph.add_node("judge", judge)
    graph.add_node("repair", repair)
    graph.add_node("assemble", build)
    graph.add_node("approval", approval)
    graph.add_node("decide", decide)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "draft")
    graph.add_edge("draft", "check")
    graph.add_edge("check", "judge")
    graph.add_conditional_edges("judge", after_judge, ["repair", "assemble"])
    graph.add_edge("repair", "check")
    graph.add_conditional_edges("assemble", after_assemble, ["approval", END])
    graph.add_edge("approval", "decide")
    graph.add_conditional_edges("decide", after_decide, ["approval", END])
    return graph.compile(checkpointer=checkpointer)


def _config(run_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": run_id}, "recursion_limit": RECURSION_LIMIT}


def _outcome(values: Mapping[str, Any]) -> TailorOutcome:
    document = values.get("document")
    return TailorOutcome(
        status=values.get("status", FAILED),
        document=codec.document_from_data(document) if document else None,
        warnings=tuple(values.get("warnings", [])),
        judged=bool(values.get("judged", False)),
        edited=bool(values.get("edited", False)),
        reason=values.get("reason"),
        problem=values.get("problem"),
    )


def start_tailor(
    graph: Any,
    run_id: str,
    *,
    kind: DocumentKind,
    language: str,
    job: Job,
    assessment: Any | None,
    posting_text: str,
) -> TailorOutcome:
    """Runs the flow until it waits for the person, or fails. Raises the session's errors when no draft exists."""
    start: TailorState = {
        "kind": kind.value,
        "language": language,
        "job": codec.job_to_data(job),
        "assessment": codec.assessment_to_data(assessment) if assessment is not None else None,
        "posting_text": posting_text,
    }
    return _outcome(graph.invoke(start, _config(run_id)))


def is_paused(graph: Any, run_id: str) -> bool:
    return bool(graph.get_state(_config(run_id)).next)


def resume_tailor(graph: Any, run_id: str, decision: Mapping[str, Any]) -> TailorOutcome:
    """Gives the person's decision to a paused run: approve, reject, or edit with new blocks."""
    if not is_paused(graph, run_id):
        raise NotPaused(run_id)
    return _outcome(graph.invoke(Command(resume=dict(decision)), _config(run_id)))
