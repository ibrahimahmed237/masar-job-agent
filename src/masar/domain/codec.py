"""Domain values as plain data and back: for the database, for a paused run, for JSON output.

Reading trusts the data: it is only used on what the writing functions of this module produced.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from masar.domain.claims import Block, BlockKind, DocumentKind, Section, Violation
from masar.domain.document import Document, DroppedBlock
from masar.domain.findings import Finding, Severity
from masar.domain.job import (
    Employment,
    Job,
    JobLocation,
    Posting,
    Requirement,
    RequirementKind,
    Seniority,
    Source,
    Sponsorship,
    Workplace,
)
from masar.domain.matching import Assessment, Flag, FlagSeverity, RequirementAssessment, Verdict

Data = dict[str, Any]


def posting_to_data(posting: Posting) -> Data:
    return {
        "source": posting.source.value,
        "company": posting.company,
        "title": posting.title,
        "text": posting.text,
        "url": posting.url,
        "location": posting.location,
        "external_id": posting.external_id,
    }


def posting_from_data(data: Mapping[str, Any]) -> Posting:
    return Posting(
        source=Source(data["source"]),
        company=data["company"],
        title=data["title"],
        text=data["text"],
        url=data.get("url"),
        location=data.get("location"),
        external_id=data.get("external_id"),
    )


def job_to_data(job: Job) -> Data:
    return {
        "title": job.title,
        "company": job.company,
        "seniority": job.seniority.value,
        "employment": job.employment.value,
        "workplace": job.workplace.value,
        "locations": [{"city": place.city, "country": place.country} for place in job.locations],
        "min_years": job.min_years,
        "sponsorship": job.sponsorship.value,
        "languages": list(job.languages),
        "requirements": [
            {
                "id": r.id,
                "text": r.text,
                "kind": r.kind.value,
                "quote": r.quote,
                "skills": list(r.skills),
                "all_skills": r.all_skills,
            }
            for r in job.requirements
        ],
    }


def job_from_data(data: Mapping[str, Any]) -> Job:
    return Job(
        title=data["title"],
        company=data["company"],
        seniority=Seniority(data["seniority"]),
        employment=Employment(data["employment"]),
        workplace=Workplace(data["workplace"]),
        locations=tuple(JobLocation(place["city"], place["country"]) for place in data["locations"]),
        min_years=data["min_years"],
        sponsorship=Sponsorship(data["sponsorship"]),
        languages=tuple(data["languages"]),
        requirements=tuple(
            Requirement(
                id=r["id"],
                text=r["text"],
                kind=RequirementKind(r["kind"]),
                quote=r["quote"],
                skills=tuple(r["skills"]),
                all_skills=r["all_skills"],
            )
            for r in data["requirements"]
        ),
    )


def findings_to_data(findings: Iterable[Finding]) -> list[Data]:
    return [{"code": f.code, "path": f.path, "message": f.message, "severity": f.severity.value} for f in findings]


def findings_from_data(data: Iterable[Mapping[str, Any]]) -> tuple[Finding, ...]:
    return tuple(Finding(f["code"], f["path"], f["message"], Severity(f["severity"])) for f in data)


def flags_to_data(flags: Iterable[Flag]) -> list[Data]:
    return [{"code": f.code, "severity": f.severity.value, "message": f.message} for f in flags]


def flags_from_data(data: Iterable[Mapping[str, Any]]) -> tuple[Flag, ...]:
    return tuple(Flag(f["code"], FlagSeverity(f["severity"]), f["message"]) for f in data)


def assessment_to_data(assessment: Assessment) -> list[Data]:
    return [
        {
            "requirement": item.requirement_id,
            "verdict": item.verdict.value,
            "evidence": list(item.evidence),
            "note": item.note,
            "by": item.by,
            "lowered_from": item.lowered_from.value if item.lowered_from else None,
            "reason": item.reason,
        }
        for item in assessment.items
    ]


def assessment_from_data(data: Iterable[Mapping[str, Any]]) -> Assessment:
    return Assessment(
        tuple(
            RequirementAssessment(
                requirement_id=item["requirement"],
                verdict=Verdict(item["verdict"]),
                evidence=tuple(item["evidence"]),
                note=item["note"],
                by=item["by"],
                lowered_from=Verdict(item["lowered_from"]) if item["lowered_from"] else None,
                reason=item["reason"],
            )
            for item in data
        )
    )


def blocks_to_data(blocks: Iterable[Block]) -> list[Data]:
    return [
        {"section": b.section.value, "kind": b.kind.value, "text": b.text, "facts": list(b.facts), "fact": b.fact}
        for b in blocks
    ]


def blocks_from_data(data: Iterable[Mapping[str, Any]]) -> tuple[Block, ...]:
    return tuple(
        Block(Section(b["section"]), BlockKind(b["kind"]), b["text"], tuple(b["facts"]), b["fact"]) for b in data
    )


def violations_to_data(violations: Iterable[Violation]) -> list[Data]:
    return [{"code": v.code, "block": v.block, "detail": v.detail} for v in violations]


def violations_from_data(data: Iterable[Mapping[str, Any]]) -> list[Violation]:
    return [Violation(v["code"], v["block"], v["detail"]) for v in data]


def document_to_data(document: Document) -> Data:
    return {
        "kind": document.kind.value,
        "language": document.language,
        "markdown": document.markdown,
        "blocks": blocks_to_data(document.blocks),
        "dropped": [{"text": d.text, "reasons": list(d.reasons)} for d in document.dropped],
    }


def document_from_data(data: Mapping[str, Any]) -> Document:
    return Document(
        kind=DocumentKind(data["kind"]),
        language=data["language"],
        markdown=data["markdown"],
        blocks=blocks_from_data(data["blocks"]),
        dropped=tuple(DroppedBlock(d["text"], tuple(d["reasons"])) for d in data["dropped"]),
    )
