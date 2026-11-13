"""Postings and jobs. A posting is raw text from a stranger; a job is what code can stand behind after reading it.

The extract step (a model) proposes a job. ``ground_job`` keeps only what the posting itself supports:
every requirement and every special field carries a quote, and the quote must be in the posting.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from masar.domain.findings import Finding, Result
from masar.domain.skills import canonical, spellings
from masar.domain.text import contains, normalize

MAX_REQUIREMENTS = 40
MAX_REQUIREMENT_TEXT = 300
MIN_QUOTE = 12

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "twelve": 12,
    "fifteen": 15,
}


class Source(StrEnum):
    MANUAL = "manual"
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"


class Seniority(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    PRINCIPAL = "principal"
    UNKNOWN = "unknown"


class Employment(StrEnum):
    FULL_TIME = "full-time"
    PART_TIME = "part-time"
    CONTRACT = "contract"
    INTERNSHIP = "internship"
    UNKNOWN = "unknown"


class Workplace(StrEnum):
    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"
    UNKNOWN = "unknown"


class Sponsorship(StrEnum):
    OFFERED = "offered"
    NOT_OFFERED = "not_offered"
    UNKNOWN = "unknown"


class RequirementKind(StrEnum):
    MUST = "must"
    NICE = "nice"


@dataclass(frozen=True, slots=True)
class Posting:
    """A job advertisement as published."""

    source: Source
    company: str
    title: str
    text: str
    url: str | None = None
    location: str | None = None
    external_id: str | None = None

    @property
    def checksum(self) -> str:
        """The identity of a posting's content: the same company, title and text are one posting."""
        content = "\n".join(normalize(part) for part in (self.company, self.title, self.text))
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class JobLocation:
    city: str | None
    country: str | None


@dataclass(frozen=True, slots=True)
class Requirement:
    id: str
    text: str
    kind: RequirementKind
    quote: str
    skills: tuple[str, ...] = ()
    all_skills: bool = False

    @property
    def skill_names(self) -> frozenset[str]:
        return frozenset(canonical(s) for s in self.skills)


@dataclass(frozen=True, slots=True)
class Job:
    """The structured reading of a posting, after grounding."""

    title: str
    company: str
    seniority: Seniority
    employment: Employment
    workplace: Workplace
    locations: tuple[JobLocation, ...]
    min_years: int | None
    sponsorship: Sponsorship
    languages: tuple[str, ...]
    requirements: tuple[Requirement, ...]

    @property
    def skills(self) -> tuple[str, ...]:
        """The skills the posting names, as written, each once."""
        seen: dict[str, str] = {}
        for requirement in self.requirements:
            for skill in requirement.skills:
                seen.setdefault(canonical(skill), skill)
        return tuple(seen.values())

    @property
    def countries(self) -> frozenset[str]:
        return frozenset(place.country for place in self.locations if place.country)

    def requirement(self, requirement_id: str) -> Requirement | None:
        return next((r for r in self.requirements if r.id == requirement_id), None)


def ground_job(candidate: Any, posting: Posting) -> Result[Job]:
    """Keeps what the posting supports and reports what was dropped. No requirement left: no job."""
    findings: list[Finding] = []
    if not isinstance(candidate, Mapping):
        return Result(None, (Finding.error("JOB-SHAPE", "", "the reading of the posting is not an object"),))
    text = posting.text

    requirements: list[Requirement] = []
    seen_quotes: set[str] = set()
    raw_requirements = candidate.get("requirements")
    for i, raw in enumerate(raw_requirements if isinstance(raw_requirements, list) else []):
        path = f"requirements[{i}]"
        if not isinstance(raw, Mapping):
            findings.append(Finding.warning("JOB-SHAPE", path, "dropped: not an object"))
            continue
        quote = _text(raw.get("quote"))
        statement = _text(raw.get("text")) or quote
        if len(normalize(quote)) < MIN_QUOTE or not contains(text, quote):
            findings.append(
                Finding.warning(
                    "JOB-QUOTE", path, f"dropped: its quote is not in the posting: {_short(quote or statement)}"
                )
            )
            continue
        if normalize(quote) in seen_quotes:
            continue
        seen_quotes.add(normalize(quote))
        if len(requirements) == MAX_REQUIREMENTS:
            findings.append(
                Finding.warning(
                    "JOB-TOO-MANY", "requirements", f"only the first {MAX_REQUIREMENTS} requirements are kept"
                )
            )
            break
        skills: list[str] = []
        raw_skills = raw.get("skills")
        for skill in raw_skills if isinstance(raw_skills, list) else []:
            name = _text(skill)
            if not name:
                continue
            if _skill_in(name, quote):
                if canonical(name) not in {canonical(s) for s in skills}:
                    skills.append(name)
            else:
                findings.append(
                    Finding.warning("JOB-SKILL", path, f"skill dropped: '{name}' is not in the requirement's quote")
                )
        kind = RequirementKind.NICE if _text(raw.get("kind")).casefold() == "nice" else RequirementKind.MUST
        requirements.append(
            Requirement(
                id=f"r{len(requirements) + 1}",
                text=statement[:MAX_REQUIREMENT_TEXT],
                kind=kind,
                quote=quote,
                skills=tuple(skills),
                all_skills=raw.get("all_skills") is True and len(skills) > 1,
            )
        )

    if not requirements:
        findings.append(
            Finding.error("JOB-EMPTY", "requirements", "no requirement of the reading is supported by the posting")
        )
        return Result(None, tuple(findings))

    job = Job(
        title=posting.title,
        company=posting.company,
        seniority=_enum(Seniority, candidate.get("seniority")),
        employment=_enum(Employment, candidate.get("employment")),
        workplace=_enum(Workplace, candidate.get("workplace")),
        locations=_locations(candidate.get("locations"), findings),
        min_years=_min_years(candidate.get("min_years"), text, findings),
        sponsorship=_sponsorship(candidate.get("sponsorship"), text, findings),
        languages=_languages(candidate.get("languages"), text, findings),
        requirements=tuple(requirements),
    )
    return Result(job, tuple(findings))


def _text(value: Any) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _short(value: str) -> str:
    return value if len(value) <= 80 else value[:77] + "..."


def _enum[E: StrEnum](kind: type[E], value: Any) -> E:
    wanted = _text(value).casefold().replace("_", "-").replace(" ", "-")
    for member in kind:
        if member.value.replace("_", "-") == wanted:
            return member
    return kind("unknown")


def _skill_in(name: str, quote: str) -> bool:
    """True when the skill, under any of its spellings, is in the quote."""
    return any(contains(quote, spelling) for spelling in spellings(name))


def _locations(raw: Any, findings: list[Finding]) -> tuple[JobLocation, ...]:
    places: list[JobLocation] = []
    for i, item in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(item, Mapping):
            continue
        city = _text(item.get("city")) or None
        country = _text(item.get("country")).upper() or None
        if country is not None and not re.fullmatch(r"[A-Z]{2}", country):
            findings.append(
                Finding.warning(
                    "JOB-LOCATION", f"locations[{i}]", f"country '{country}' is not a two-letter code; kept as unknown"
                )
            )
            country = None
        if city or country:
            places.append(JobLocation(city, country))
    return tuple(dict.fromkeys(places))


def _min_years(raw: Any, text: str, findings: list[Finding]) -> int | None:
    if raw is None:
        return None
    value = raw.get("value") if isinstance(raw, Mapping) else None
    quote = _text(raw.get("quote")) if isinstance(raw, Mapping) else ""
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 40:
        findings.append(Finding.warning("JOB-YEARS", "min_years", "dropped: not a whole number of years"))
        return None
    said = normalize(quote)
    in_words = any(number == value and re.search(rf"\b{word}\b", said) for word, number in _NUMBER_WORDS.items())
    if not contains(text, quote) or not (re.search(rf"(?<!\d){value}(?!\d)", said) or in_words):
        findings.append(
            Finding.warning(
                "JOB-YEARS", "min_years", f"dropped: the posting does not say {value} years in the quoted words"
            )
        )
        return None
    return value


def _sponsorship(raw: Any, text: str, findings: list[Finding]) -> Sponsorship:
    if not isinstance(raw, Mapping):
        return Sponsorship.UNKNOWN
    status = _enum(Sponsorship, raw.get("status"))
    if status is Sponsorship.UNKNOWN:
        return status
    quote = _text(raw.get("quote"))
    if len(normalize(quote)) < MIN_QUOTE or not contains(text, quote):
        findings.append(
            Finding.warning("JOB-SPONSORSHIP", "sponsorship", "set to unknown: its quote is not in the posting")
        )
        return Sponsorship.UNKNOWN
    return status


def _languages(raw: Any, text: str, findings: list[Finding]) -> tuple[str, ...]:
    codes: list[str] = []
    for i, item in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(item, Mapping):
            continue
        code = _text(item.get("code")).casefold()
        quote = _text(item.get("quote"))
        if not re.fullmatch(r"[a-z]{2}", code) or not contains(text, quote):
            findings.append(
                Finding.warning(
                    "JOB-LANGUAGE", f"languages[{i}]", "dropped: not a language code with a quote from the posting"
                )
            )
            continue
        if code not in codes:
            codes.append(code)
    return tuple(codes)
