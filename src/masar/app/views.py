"""Records as plain data, for JSON output and for tool answers. One place, so both hosts say the same."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from masar.app.service import AssessResult, DraftResult, FactView, FetchReport, JobDetail, ProfileReport, TodayItem
from masar.domain import codec
from masar.domain.claims import Violation
from masar.domain.findings import Finding
from masar.ports.store import (
    ApplicationEvent,
    ApplicationRecord,
    DocumentRecord,
    JobSummary,
    RunRecord,
    RunStep,
    StoredPosting,
)

Data = dict[str, Any]


def _time(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def findings(items: tuple[Finding, ...]) -> list[Data]:
    return codec.findings_to_data(items)


def profile(report: ProfileReport) -> Data:
    return {
        "ok": report.ok,
        "errors": findings(report.errors),
        "warnings": findings(report.warnings),
        "years_of_experience": report.years,
        "facts": report.facts,
        "skills": list(report.skills),
        "checksum": report.checksum,
    }


def fact(view: FactView) -> Data:
    return {
        "id": view.id,
        "kind": view.kind,
        "text": view.text,
        "skills": list(view.skills),
        "org": view.org,
        "role": view.role,
        "period": view.period,
    }


def posting(stored: StoredPosting, *, text: bool = False) -> Data:
    data: Data = {
        "id": stored.id,
        "company": stored.posting.company,
        "title": stored.posting.title,
        "source": stored.posting.source.value,
        "url": stored.posting.url,
        "location": stored.posting.location,
        "fetched_at": _time(stored.fetched_at),
    }
    if text:
        data["text"] = stored.posting.text
    return data


def fetch_report(report: FetchReport) -> Data:
    return {
        "source": report.board.source.value,
        "board": report.board.board,
        "company": report.board.company,
        "new": report.new,
        "known": report.known,
        "filtered": report.filtered,
        "skipped": report.skipped,
        "error": report.error,
    }


def job_summary(summary: JobSummary) -> Data:
    return {
        "id": summary.posting_id,
        "company": summary.company,
        "title": summary.title,
        "location": summary.location,
        "url": summary.url,
        "status": summary.status,
        "score": summary.score,
        "recommendation": summary.recommendation.value if summary.recommendation else None,
        "flags": codec.flags_to_data(summary.flags),
        "state": summary.state.value,
    }


def job_detail(detail: JobDetail) -> Data:
    record = detail.job
    data: Data = {
        **posting(detail.posting),
        "state": detail.application.state.value,
        "status": record.status if record else "new",
        "score": record.score if record else None,
        "recommendation": record.recommendation.value if record and record.recommendation else None,
        "stale": detail.stale,
        "flags": codec.flags_to_data(record.flags) if record else [],
        "findings": findings(record.findings) if record else [],
        "job": None,
        "requirements": [],
    }
    if record and record.job:
        job = record.job
        data["job"] = {
            "seniority": job.seniority.value,
            "employment": job.employment.value,
            "workplace": job.workplace.value,
            "locations": [{"city": place.city, "country": place.country} for place in job.locations],
            "min_years": job.min_years,
            "sponsorship": job.sponsorship.value,
            "languages": list(job.languages),
        }
        for requirement in job.requirements:
            item = record.assessment.of(requirement.id) if record.assessment else None
            data["requirements"].append(
                {
                    "id": requirement.id,
                    "kind": requirement.kind.value,
                    "text": requirement.text,
                    "quote": requirement.quote,
                    "skills": list(requirement.skills),
                    "all_skills": requirement.all_skills,
                    "verdict": item.verdict.value if item else None,
                    "evidence": list(item.evidence) if item else [],
                    "note": item.note if item else "",
                    "by": item.by if item else None,
                    "lowered_from": item.lowered_from.value if item and item.lowered_from else None,
                    "reason": item.reason if item else None,
                }
            )
    return data


def assess_result(result: AssessResult) -> Data:
    record = result.record
    return {
        "id": result.posting_id,
        "run": result.run_id,
        "status": record.status,
        "reason": result.reason,
        "score": record.score,
        "recommendation": record.recommendation.value if record.recommendation else None,
        "flags": codec.flags_to_data(record.flags),
        "findings": findings(record.findings),
    }


def document(record: DocumentRecord, *, private: bool) -> Data:
    """A draft. ``private`` adds the finished text, which holds the person's name and contacts:
    for the person's own terminal, never for an assistant."""
    data: Data = {
        "id": record.id,
        "job": record.posting_id,
        "kind": record.kind.value,
        "language": record.language,
        "status": record.status,
        "judged": record.judged,
        "edited": record.edited,
        "reason": record.reason,
        "warnings": list(record.warnings),
        "blocks": codec.blocks_to_data(record.blocks),
        "dropped": [{"text": dropped.text, "reasons": list(dropped.reasons)} for dropped in record.dropped],
        "run": record.run_id,
        "created_at": _time(record.created_at),
        "decided_at": _time(record.decided_at),
    }
    if private:
        data["markdown"] = record.markdown
    return data


def draft_result(result: DraftResult, *, private: bool) -> Data:
    return {
        **document(result.document, private=private),
        "problem": result.problem,
        "moved_to_drafted": result.moved_to_drafted,
    }


def application(record: ApplicationRecord, stored: StoredPosting) -> Data:
    return {
        "id": record.posting_id,
        "company": stored.posting.company,
        "title": stored.posting.title,
        "state": record.state.value,
        "updated_at": _time(record.updated_at),
    }


def event(item: ApplicationEvent) -> Data:
    return {
        "from": item.from_state.value if item.from_state else None,
        "to": item.to_state.value,
        "note": item.note,
        "at": _time(item.at),
    }


def today_item(item: TodayItem) -> Data:
    return {
        "id": item.posting_id,
        "company": item.company,
        "title": item.title,
        "reason": item.reason.value,
        "days": item.days,
    }


def run(record: RunRecord, steps: list[RunStep] | None = None) -> Data:
    data: Data = {
        "id": record.id,
        "kind": record.kind,
        "job": record.posting_id,
        "status": record.status,
        "reason": record.reason,
        "tokens_in": record.tokens_in,
        "tokens_out": record.tokens_out,
        "started_at": _time(record.started_at),
        "ended_at": _time(record.ended_at),
    }
    if steps is not None:
        data["steps"] = [
            {
                "step": step.step,
                "model": step.model,
                "prompt_version": step.prompt_version,
                "tokens_in": step.tokens_in,
                "tokens_out": step.tokens_out,
                "duration_ms": step.duration_ms,
                "input_checksum": step.input_checksum,
                "output": step.output,
            }
            for step in steps
        ]
    return data


def violations(found: list[Violation]) -> Data:
    return {"ok": not found, "violations": [{"code": v.code, "detail": v.detail} for v in found]}
