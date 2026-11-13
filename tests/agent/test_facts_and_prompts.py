"""Which facts a model is shown, and what the prompts say."""

from __future__ import annotations

from typing import Any

from masar.agent.facts import MAX_ASSESS_FACTS, MAX_DRAFT_FACTS, facts_for_assessment, facts_for_draft
from masar.agent.prompts import draft_messages, fact_view, repair_messages
from masar.domain.claims import Block, BlockKind, DocumentKind, Section, Violation
from masar.domain.matching import check_evidence
from tests.support.career import TODAY, career_with, example_career, example_data
from tests.support.jobs import example_job
from tests.support.postings import assessment

JOB = example_job()


def many_facts(count: int) -> list[Any]:
    facts: list[Any] = example_data()["facts"]
    for i in range(count):
        facts.append(
            {
                "id": f"extra-{i:03d}",
                "kind": "project",
                "text": f"Wrote small tool number {i} for the team.",
                "skills": ["Bash"],
            }
        )
    return facts


def test_all_facts_are_assessed_when_they_fit() -> None:
    career = example_career()
    assert facts_for_assessment(career, JOB, TODAY) == list(career.facts)


def test_a_large_career_file_sends_the_relevant_facts_first() -> None:
    career = career_with(facts=many_facts(80))
    chosen = [fact.id for fact in facts_for_assessment(career, JOB, TODAY)]

    assert len(chosen) == MAX_ASSESS_FACTS
    # Facts that share a skill with the job come first, the newest first; then the other experience.
    assert chosen[:5] == ["acme-allocation", "acme-receiving", "acme-support-agent", "nimbus-apis", "nimbus-payments"]
    assert "ledger-project" in chosen  # PostgreSQL


def test_a_draft_builds_on_at_most_twelve_facts_with_the_evidence_first() -> None:
    career = career_with(facts=many_facts(30))
    checked = check_evidence(JOB, career, assessment()).unwrap()
    chosen = [fact.id for fact in facts_for_draft(career, JOB, checked, TODAY)]

    assert len(chosen) == MAX_DRAFT_FACTS
    assert chosen[:2] == ["acme-allocation", "nimbus-apis"]  # the evidence of r1, in the order it was given


def test_a_draft_without_an_assessment_starts_from_shared_skills() -> None:
    chosen = [fact.id for fact in facts_for_draft(example_career(), JOB, None, TODAY)]
    assert chosen[0] == "acme-allocation"
    assert chosen[-1] in {"tooling", "bsc"}


def test_a_fact_is_shown_without_empty_fields() -> None:
    career = example_career()
    assert fact_view(career.facts[0]) == {
        "id": "acme-allocation",
        "kind": "experience",
        "text": "Built an event-driven inventory allocation service that raised store availability to 93%.",
        "org": "Acme Retail",
        "role": "Software Engineer",
        "period": "2023-03 to present",
        "skills": ["NestJS", "TypeScript", "Kafka", "PostgreSQL"],
    }
    assert set(fact_view(career.facts[5])) == {"id", "kind", "text", "skills"}


def system_for(language: str = "en", metrics: bool = True, years: int = 5, kind: DocumentKind = DocumentKind.CV) -> str:
    career = example_career()
    return draft_messages(kind, language, JOB, None, career.facts, metrics=metrics, years=years)[0].content


def test_the_draft_prompt_names_the_language() -> None:
    assert "Write in English." in system_for("en")
    assert "Modern Standard Arabic" in system_for("ar")
    assert "Write in English." not in system_for("ar")


def test_the_draft_prompt_follows_the_style_of_the_career_file() -> None:
    assert "Numbers come from the cited facts only." in system_for(metrics=True)
    assert "Write no numbers." in system_for(metrics=False)
    assert '"5 years"' in system_for(years=5)
    assert "years of experience" not in system_for(years=0)


def test_each_document_kind_has_its_own_rules() -> None:
    assert '"experience": bullets' in system_for(kind=DocumentKind.CV)
    assert "2 to 6 paragraphs" in system_for(kind=DocumentKind.COVER)
    assert "1 to 4 short paragraphs" in system_for(kind=DocumentKind.OUTREACH)


def test_the_repair_prompt_shows_only_the_failed_blocks_with_their_reasons() -> None:
    blocks = [
        Block(Section.SUMMARY, BlockKind.CLAIM, "Good block.", ("acme-allocation",)),
        Block(Section.SUMMARY, BlockKind.CLAIM, "Bad block with Rust.", ("acme-allocation",)),
    ]
    violations = [Violation("UNSUPPORTED_SKILL", 1, "Rust"), Violation("TOO_LONG", 9, "not a block of this draft")]
    system, user = repair_messages(blocks, violations, example_career().facts, "ar", metrics=False, years=5)

    assert "Bad block with Rust." in user.content
    assert "Good block." not in user.content
    assert '"code": "UNSUPPORTED_SKILL"' in user.content
    assert "Write no numbers." in system.content
    assert "Modern Standard Arabic" in system.content
