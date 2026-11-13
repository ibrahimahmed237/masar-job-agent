"""Which facts a model is shown. Code decides, by rules that can be read."""

from __future__ import annotations

from datetime import date

from masar.domain.career import Career, Fact, FactKind
from masar.domain.job import Job
from masar.domain.matching import Assessment
from masar.domain.skills import canonical

MAX_ASSESS_FACTS = 60
MAX_DRAFT_FACTS = 12


def _recency(fact: Fact, today: date) -> tuple[int, int]:
    if fact.period is None:
        return (0, 0)
    return (fact.period.end_at(today).index, fact.period.start.index)


def _by_relevance(career: Career, job: Job, today: date, first: tuple[str, ...] = ()) -> list[Fact]:
    """Named facts first, then facts that share a skill with the job, then experience, newest first, then the rest."""
    wanted = {canonical(skill) for skill in job.skills}
    order: dict[str, Fact] = {}
    for fact_id in first:
        fact = career.fact(fact_id)
        if fact is not None:
            order.setdefault(fact.id, fact)
    newest_first = sorted(career.facts, key=lambda fact: _recency(fact, today), reverse=True)
    for fact in newest_first:
        if fact.skill_names & wanted:
            order.setdefault(fact.id, fact)
    for fact in newest_first:
        if fact.kind is FactKind.EXPERIENCE:
            order.setdefault(fact.id, fact)
    for fact in career.facts:
        order.setdefault(fact.id, fact)
    return list(order.values())


def facts_for_assessment(career: Career, job: Job, today: date) -> list[Fact]:
    """All facts when they fit; otherwise the most relevant ones."""
    if len(career.facts) <= MAX_ASSESS_FACTS:
        return list(career.facts)
    return _by_relevance(career, job, today)[:MAX_ASSESS_FACTS]


def facts_for_draft(career: Career, job: Job, assessment: Assessment | None, today: date) -> list[Fact]:
    """The facts a draft may build on: the evidence of the assessment first."""
    evidence = tuple(fact_id for item in assessment.items for fact_id in item.evidence) if assessment else ()
    return _by_relevance(career, job, today, evidence)[:MAX_DRAFT_FACTS]
