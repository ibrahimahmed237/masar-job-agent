"""The intake flow: a posting becomes a job with flags, verdicts and a score.

Two steps ask a model. Each is followed by code that keeps only what can be checked.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from masar.agent.facts import facts_for_assessment
from masar.agent.prompts import MAX_POSTING_CHARS, assess_messages, extract_messages
from masar.agent.session import ModelSession
from masar.domain import codec
from masar.domain.career import Career
from masar.domain.findings import Finding
from masar.domain.job import Job, Posting, ground_job
from masar.domain.matching import (
    Assessment,
    Flag,
    FlagSeverity,
    Recommendation,
    ScoreSettings,
    check_evidence,
    recommend,
    score,
    screen,
)

ASSESSED = "assessed"
SCREENED = "screened"  # a blocker was found and the assessment was skipped
UNREADABLE = "unreadable"


class IntakeState(TypedDict, total=False):
    posting: dict[str, Any]
    candidate: dict[str, Any]
    job: dict[str, Any] | None
    findings: list[dict[str, Any]]
    flags: list[dict[str, Any]]
    raw_assessment: dict[str, Any]
    assessment: list[dict[str, Any]] | None
    score: int | None
    recommendation: str | None
    status: str


@dataclass(frozen=True)
class IntakeDeps:
    """What the flow works with. Given when the graph is built, so the state holds only what the run produced."""

    session: ModelSession
    career: Career
    today: date
    skip_on_blocker: bool = True
    settings: ScoreSettings = field(default_factory=ScoreSettings)


@dataclass(frozen=True)
class IntakeResult:
    status: str
    job: Job | None
    findings: tuple[Finding, ...]
    flags: tuple[Flag, ...]
    assessment: Assessment | None
    score: int | None
    recommendation: Recommendation | None


def _requirements_given(value: dict[str, Any]) -> str | None:
    return None if isinstance(value.get("requirements"), list) else 'the object needs a "requirements" list'


def _assessments_given(value: dict[str, Any]) -> str | None:
    return None if isinstance(value.get("assessments"), list) else 'the object needs an "assessments" list'


def build_intake_graph(deps: IntakeDeps) -> Any:
    def posting_of(state: IntakeState) -> Posting:
        return codec.posting_from_data(state["posting"])

    def extract(state: IntakeState) -> IntakeState:
        posting = posting_of(state)
        messages = extract_messages(posting.title, posting.company, posting.text)
        return {"candidate": deps.session.ask_json("extract", messages, _requirements_given)}

    def ground(state: IntakeState) -> IntakeState:
        posting = posting_of(state)
        findings: list[Finding] = []
        if len(posting.text) > MAX_POSTING_CHARS:
            findings.append(
                Finding.warning(
                    "JOB-TRUNCATED", "text", f"only the first {MAX_POSTING_CHARS} characters of the posting were read"
                )
            )
            # What the model did not see cannot hold its quotes.
            posting = replace(posting, text=posting.text[:MAX_POSTING_CHARS])
        result = ground_job(state["candidate"], posting)
        findings += result.findings
        if result.value is None:
            return {"job": None, "findings": codec.findings_to_data(findings), "status": UNREADABLE}
        return {"job": codec.job_to_data(result.value), "findings": codec.findings_to_data(findings)}

    def screen_job(state: IntakeState) -> IntakeState:
        job = codec.job_from_data(state["job"] or {})
        return {"flags": codec.flags_to_data(screen(job, deps.career, deps.today))}

    def assess(state: IntakeState) -> IntakeState:
        job = codec.job_from_data(state["job"] or {})
        facts = facts_for_assessment(deps.career, job, deps.today)
        return {"raw_assessment": deps.session.ask_json("assess", assess_messages(job, facts), _assessments_given)}

    def evidence(state: IntakeState) -> IntakeState:
        job = codec.job_from_data(state["job"] or {})
        result = check_evidence(job, deps.career, state["raw_assessment"])
        findings = [*state.get("findings", []), *codec.findings_to_data(result.findings)]
        return {"assessment": codec.assessment_to_data(result.unwrap()), "findings": findings}

    def score_job(state: IntakeState) -> IntakeState:
        job = codec.job_from_data(state["job"] or {})
        flags = codec.flags_from_data(state.get("flags", []))
        data = state.get("assessment")
        if data is None:
            return {"score": None, "recommendation": recommend(None, flags, deps.settings).value, "status": SCREENED}
        points = score(job, codec.assessment_from_data(data), deps.settings)
        return {"score": points, "recommendation": recommend(points, flags, deps.settings).value, "status": ASSESSED}

    def after_ground(state: IntakeState) -> str:
        return END if state.get("job") is None else "screen"

    def after_screen(state: IntakeState) -> str:
        blocked = any(flag["severity"] == FlagSeverity.BLOCKER.value for flag in state.get("flags", []))
        return "score" if blocked and deps.skip_on_blocker else "assess"

    graph = StateGraph(IntakeState)
    graph.add_node("extract", extract)
    graph.add_node("ground", ground)
    graph.add_node("screen", screen_job)
    graph.add_node("assess", assess)
    graph.add_node("evidence", evidence)
    graph.add_node("score", score_job)
    graph.add_edge(START, "extract")
    graph.add_edge("extract", "ground")
    graph.add_conditional_edges("ground", after_ground, ["screen", END])
    graph.add_conditional_edges("screen", after_screen, ["assess", "score"])
    graph.add_edge("assess", "evidence")
    graph.add_edge("evidence", "score")
    graph.add_edge("score", END)
    return graph.compile()


def run_intake(deps: IntakeDeps, posting: Posting) -> IntakeResult:
    """Runs the flow once. Raises ``BudgetExceeded``, ``ModelOutputError`` or ``ModelUnavailable``."""
    state: IntakeState = build_intake_graph(deps).invoke({"posting": codec.posting_to_data(posting)})
    job = state.get("job")
    assessment = state.get("assessment")
    recommendation = state.get("recommendation")
    return IntakeResult(
        status=state["status"],
        job=codec.job_from_data(job) if job else None,
        findings=codec.findings_from_data(state.get("findings", [])),
        flags=codec.flags_from_data(state.get("flags", [])),
        assessment=codec.assessment_from_data(assessment) if assessment is not None else None,
        score=state.get("score"),
        recommendation=Recommendation(recommendation) if recommendation else None,
    )
