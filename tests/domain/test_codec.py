"""Plain data and back: nothing is lost on the way to the database or to a paused run."""

from __future__ import annotations

import json

from masar.domain import codec
from masar.domain.claims import Block, BlockKind, DocumentKind, Section, Violation
from masar.domain.document import Document, DroppedBlock
from masar.domain.findings import Finding
from masar.domain.job import JobLocation, Posting, Source
from masar.domain.matching import Assessment, Flag, FlagSeverity, RequirementAssessment, Verdict
from tests.support.jobs import example_job


def through_json(data: object) -> object:
    return json.loads(json.dumps(data, ensure_ascii=False))


def test_a_posting_survives() -> None:
    posting = Posting(
        Source.LEVER, "Tamween", "Backend Engineer", "Text ـ نص", "https://example.com/1", "Riyadh", "abc-1"
    )
    assert codec.posting_from_data(through_json(codec.posting_to_data(posting))) == posting  # type: ignore[arg-type]
    bare = Posting(Source.MANUAL, "Tamween", "Backend Engineer", "Text")
    assert codec.posting_from_data(through_json(codec.posting_to_data(bare))) == bare  # type: ignore[arg-type]


def test_a_job_survives_with_every_field() -> None:
    job = example_job(locations=(JobLocation("Riyadh", "SA"), JobLocation(None, "AE")), min_years=None)
    again = codec.job_from_data(through_json(codec.job_to_data(job)))  # type: ignore[arg-type]
    assert again == job
    assert again.requirements[2].all_skills is True
    assert again.requirements[3].kind.value == "nice"


def test_an_assessment_survives() -> None:
    assessment = Assessment(
        (
            RequirementAssessment("r1", Verdict.MET, ("a", "b"), "note"),
            RequirementAssessment("r2", Verdict.PARTIAL, ("a",), "", "code", Verdict.MET, "no fact shows: Kafka"),
            RequirementAssessment("r3", Verdict.MISSING, by="code", reason="not assessed"),
        )
    )
    assert codec.assessment_from_data(through_json(codec.assessment_to_data(assessment))) == assessment  # type: ignore[arg-type]


def test_flags_findings_and_violations_survive() -> None:
    flags = (Flag("NO_RELOCATION", FlagSeverity.BLOCKER, "m"), Flag("YEARS_BELOW", FlagSeverity.WARNING, "n"))
    assert codec.flags_from_data(through_json(codec.flags_to_data(flags))) == flags  # type: ignore[arg-type]
    findings = (Finding.error("A", "p", "m"), Finding.warning("B", "q", "n"))
    assert codec.findings_from_data(through_json(codec.findings_to_data(findings))) == findings  # type: ignore[arg-type]
    violations = [Violation("TOO_LONG", 3, "d")]
    assert codec.violations_from_data(through_json(codec.violations_to_data(violations))) == violations  # type: ignore[arg-type]


def test_a_document_survives_with_its_blocks_and_what_was_dropped() -> None:
    blocks = (
        Block(Section.EXPERIENCE, BlockKind.CLAIM, "Built it.", ("acme-allocation", "x"), "acme-allocation"),
        Block(Section.BODY, BlockKind.PLAIN, "Hello."),
    )
    document = Document(DocumentKind.COVER, "ar", "# نص", blocks, (DroppedBlock("Bad.", ("A: b", "C: d")),))
    assert codec.document_from_data(through_json(codec.document_to_data(document))) == document  # type: ignore[arg-type]
    assert codec.blocks_from_data(through_json(codec.blocks_to_data(blocks))) == blocks  # type: ignore[arg-type]
