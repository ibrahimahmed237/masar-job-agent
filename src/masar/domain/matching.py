"""Screen a job against the person's limits, check the evidence of an assessment, and compute the score.

All of it is code (ADR-0007). A model proposes verdicts; nothing here lets it set a number or raise a verdict.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any

from masar.domain.career import Career, Limits
from masar.domain.findings import Finding, Result
from masar.domain.job import Job, RequirementKind, Seniority, Sponsorship, Workplace
from masar.domain.skills import display
from masar.domain.text import normalize

MAX_NOTE = 300
MAX_EVIDENCE = 6

# What a seniority word usually means in years, used only when the posting gives no number.
_USUAL_YEARS = {Seniority.JUNIOR: 0, Seniority.MID: 2, Seniority.SENIOR: 5, Seniority.LEAD: 7, Seniority.PRINCIPAL: 10}


class FlagSeverity(StrEnum):
    BLOCKER = "blocker"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class Flag:
    code: str
    severity: FlagSeverity
    message: str


def title_matches(title: str, limits: Limits) -> bool:
    """The cheap filter before any model call: one wanted word in the title, and no unwanted one."""
    text = normalize(title).replace("-", "")

    def has(word: str) -> bool:
        return re.search(rf"(?<![a-z0-9]){re.escape(normalize(word).replace('-', ''))}(?![a-z0-9])", text) is not None

    if any(has(word) for word in limits.title_exclude):
        return False
    return not limits.title_keywords or any(has(word) for word in limits.title_keywords)


def screen(job: Job, career: Career, today: date) -> tuple[Flag, ...]:
    """Flags for a job. Missing information in the posting is a warning, never a blocker."""
    flags: list[Flag] = []
    person, limits = career.person, career.limits

    def add(code: str, blocker: bool, message: str) -> None:
        flags.append(Flag(code, FlagSeverity.BLOCKER if blocker else FlagSeverity.WARNING, message))

    if normalize(job.company) in {normalize(c) for c in limits.exclude_companies}:
        add("COMPANY_EXCLUDED", True, f"{job.company} is on your list of excluded companies")

    if limits.employment and job.employment.value != "unknown" and job.employment.value not in limits.employment:
        add(
            "EMPLOYMENT_NOT_WANTED",
            True,
            f"the job is {job.employment.value}; you accept: {', '.join(sorted(limits.employment))}",
        )

    remote = job.workplace is Workplace.REMOTE
    # A posting that does not say where the work happens may be remote. Its location rules can only warn.
    on_site = job.workplace in (Workplace.ONSITE, Workplace.HYBRID)
    countries = job.countries
    every_place_known = bool(job.locations) and all(place.country for place in job.locations)

    if job.workplace is Workplace.UNKNOWN:
        add("WORKPLACE_UNKNOWN", False, "the posting does not say if the job is on-site, hybrid or remote")

    if remote and not limits.remote:
        add("REMOTE_NOT_WANTED", True, "the job is remote and you do not accept remote jobs")

    if not remote:
        if not countries:
            add("LOCATION_UNKNOWN", False, "the posting names no country")
        if limits.countries and every_place_known and not countries & limits.countries:
            add("COUNTRY_NOT_WANTED", on_site, f"the job is in {_list(countries)}; you want: {_list(limits.countries)}")
        home = person.location.country if person.location else None
        if not limits.relocation and home and countries and home not in countries:
            add("NO_RELOCATION", on_site, f"the job is in {_list(countries)} and you do not accept relocation")
        if countries and not countries & person.work_authorization:
            if not person.work_authorization:
                add("SPONSORSHIP_UNKNOWN", False, "your career file does not say where you may work without a visa")
            elif job.sponsorship is Sponsorship.NOT_OFFERED:
                add(
                    "SPONSORSHIP_NOT_OFFERED",
                    on_site,
                    f"you need a visa for {_list(countries)} and the posting says it does not sponsor",
                )
            elif job.sponsorship is Sponsorship.UNKNOWN:
                add(
                    "SPONSORSHIP_UNKNOWN",
                    False,
                    f"you need a visa for {_list(countries)} and the posting does not say if it sponsors",
                )
    elif countries and person.work_authorization and not countries & person.work_authorization:
        add(
            "REMOTE_REGION",
            False,
            f"the job is remote but names {_list(countries)}: check that you may work from where you are",
        )

    years = career.years_of_experience(today)
    if job.min_years is not None:
        if job.min_years > years + limits.years_gap_allowed:
            add("YEARS_FAR_BELOW", True, f"the posting asks for {job.min_years} years; you have {_years(years)}")
        elif job.min_years > years:
            add("YEARS_BELOW", False, f"the posting asks for {job.min_years} years; you have {_years(years)}")
    elif job.seniority in _USUAL_YEARS and _USUAL_YEARS[job.seniority] > years + limits.years_gap_allowed:
        usual = _USUAL_YEARS[job.seniority]
        add(
            "SENIORITY_ABOVE",
            False,
            f"a {job.seniority.value} role usually means about {usual} years; you have {_years(years)}",
        )

    spoken = {language.code for language in person.languages}
    missing = [code for code in job.languages if code not in spoken]
    if spoken and missing:
        add("LANGUAGE_MISSING", True, f"the posting requires a language you did not list: {', '.join(missing)}")

    return tuple(flags)


def _list(codes: frozenset[str]) -> str:
    return ", ".join(sorted(codes))


def _years(years: float) -> str:
    whole = int(years)
    return f"{whole} year{'s' if whole != 1 else ''}" if years == whole else f"{years:.1f} years"


class Verdict(StrEnum):
    MET = "met"
    PARTIAL = "partial"
    MISSING = "missing"


_RANK = {Verdict.MISSING: 0, Verdict.PARTIAL: 1, Verdict.MET: 2}
_VALUE = {Verdict.MISSING: 0.0, Verdict.PARTIAL: 0.5, Verdict.MET: 1.0}


@dataclass(frozen=True, slots=True)
class RequirementAssessment:
    """The verdict on one requirement, and who stands behind it."""

    requirement_id: str
    verdict: Verdict
    evidence: tuple[str, ...] = ()
    note: str = ""
    by: str = "model"  # "model", or "code" when a check lowered or set the verdict
    lowered_from: Verdict | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class Assessment:
    items: tuple[RequirementAssessment, ...]

    def of(self, requirement_id: str) -> RequirementAssessment | None:
        return next((i for i in self.items if i.requirement_id == requirement_id), None)


def check_evidence(job: Job, career: Career, raw: Any) -> Result[Assessment]:
    """The assessment that code can stand behind.

    It may lower a verdict, and add evidence it can verify itself. It never raises a verdict.
    """
    findings: list[Finding] = []
    proposed: dict[str, Mapping[str, Any]] = {}
    entries = raw.get("assessments") if isinstance(raw, Mapping) else raw
    for i, entry in enumerate(entries if isinstance(entries, list) else []):
        requirement_id = entry.get("requirement") if isinstance(entry, Mapping) else None
        if not isinstance(requirement_id, str) or job.requirement(requirement_id) is None or requirement_id in proposed:
            findings.append(
                Finding.warning(
                    "EVIDENCE-UNKNOWN-REQUIREMENT",
                    f"assessments[{i}]",
                    "ignored: not a requirement of this job, or given twice",
                )
            )
            continue
        proposed[requirement_id] = entry

    items: list[RequirementAssessment] = []
    for requirement in job.requirements:
        path = f"requirements.{requirement.id}"
        entry = proposed.get(requirement.id)
        if entry is None:
            findings.append(
                Finding.warning("EVIDENCE-NOT-ASSESSED", path, "the model gave no verdict; counted as missing")
            )
            items.append(RequirementAssessment(requirement.id, Verdict.MISSING, by="code", reason="not assessed"))
            continue

        said = _verdict(entry.get("verdict"))
        verdict, reason = said, None
        raw_note = entry.get("note")
        note = raw_note if isinstance(raw_note, str) else ""
        evidence: list[str] = []
        raw_evidence = entry.get("evidence")
        for fact_id in raw_evidence if isinstance(raw_evidence, list) else []:
            if isinstance(fact_id, str) and fact_id in career.fact_ids:
                if fact_id not in evidence:
                    evidence.append(fact_id)
            else:
                findings.append(
                    Finding.warning(
                        "EVIDENCE-UNKNOWN-FACT", path, f"evidence dropped: '{fact_id}' is not a fact of the career file"
                    )
                )

        if requirement.skills:
            has = {name for name in requirement.skill_names if career.facts_with_skill(name)}
            if verdict is Verdict.MISSING:
                if has:
                    shown = ", ".join(sorted(display(name) for name in has))
                    findings.append(
                        Finding.warning(
                            "EVIDENCE-OVERLOOKED", path, f"the model said missing, but your facts show: {shown}"
                        )
                    )
            else:
                # Evidence that code can verify by itself: the facts that carry the named skills.
                for name in sorted(has):
                    evidence += [f.id for f in career.facts_with_skill(name) if f.id not in evidence]
                enough = has == requirement.skill_names if requirement.all_skills else bool(has)
                if verdict is Verdict.MET and not enough:
                    # Some of the named skills: partly true. None of them: the model said something that
                    # code can see is false, and nothing of it stands.
                    lacking = ", ".join(sorted(display(name) for name in requirement.skill_names - has))
                    verdict, reason = (Verdict.PARTIAL if has else Verdict.MISSING), f"no fact shows: {lacking}"
                    findings.append(Finding.warning("EVIDENCE-SKILL", path, f"lowered to {verdict.value}: {reason}"))

        if verdict is not Verdict.MISSING and not evidence:
            verdict, reason = Verdict.MISSING, "no evidence"
            findings.append(
                Finding.warning("EVIDENCE-NONE", path, f"lowered to missing: '{said.value}' with no fact behind it")
            )

        lowered = verdict is not said
        items.append(
            RequirementAssessment(
                requirement_id=requirement.id,
                verdict=verdict,
                evidence=tuple(evidence[:MAX_EVIDENCE]) if verdict is not Verdict.MISSING else (),
                note=" ".join(note.split())[:MAX_NOTE],
                by="code" if lowered else "model",
                lowered_from=said if lowered else None,
                reason=reason,
            )
        )
    return Result(Assessment(tuple(items)), tuple(findings))


def _verdict(value: Any) -> Verdict:
    text = value.strip().casefold() if isinstance(value, str) else ""
    return Verdict(text) if text in {v.value for v in Verdict} else Verdict.MISSING


@dataclass(frozen=True, slots=True)
class ScoreSettings:
    must_weight: int = 3
    nice_weight: int = 1
    apply_from: int = 70
    maybe_from: int = 50


class Recommendation(StrEnum):
    APPLY = "apply"
    MAYBE = "maybe"
    SKIP = "skip"


def score(job: Job, assessment: Assessment, settings: ScoreSettings = ScoreSettings()) -> int | None:
    """0 to 100 from the verdicts and their weights. A job with no requirements has no score."""
    total = 0.0
    weight_sum = 0
    for requirement in job.requirements:
        weight = settings.must_weight if requirement.kind is RequirementKind.MUST else settings.nice_weight
        item = assessment.of(requirement.id)
        total += weight * _VALUE[item.verdict if item else Verdict.MISSING]
        weight_sum += weight
    if weight_sum == 0:
        return None
    return int(100 * total / weight_sum + 0.5)


def recommend(points: int | None, flags: tuple[Flag, ...], settings: ScoreSettings = ScoreSettings()) -> Recommendation:
    if any(flag.severity is FlagSeverity.BLOCKER for flag in flags):
        return Recommendation.SKIP
    if points is None:
        return Recommendation.MAYBE
    if points >= settings.apply_from:
        return Recommendation.APPLY
    return Recommendation.MAYBE if points >= settings.maybe_from else Recommendation.SKIP


def is_lower_or_equal(after: Verdict, before: Verdict) -> bool:
    """True when a check did not raise a verdict. Used by the tests of the evidence checks."""
    return _RANK[after] <= _RANK[before]
