"""The career file: who the person is, what they will not accept, and the facts that may be claimed about them.

The person writes it; Masar reads it and never writes it (ADR-0008). ``parse_career`` turns the loaded
YAML into a ``Career`` and reports every broken rule with its path.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any

from masar.domain.findings import Finding, Result
from masar.domain.skills import canonical, canonical_set

_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,38}[a-z0-9]$")
_YEAR_MONTH = re.compile(r"^(\d{4})-(\d{2})$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_LANGUAGE = re.compile(r"^[a-z]{2}$")

MIN_TEXT = 10
MAX_TEXT = 600


class FactKind(StrEnum):
    EXPERIENCE = "experience"
    PROJECT = "project"
    EDUCATION = "education"
    SKILL = "skill"
    OTHER = "other"


@dataclass(frozen=True, slots=True, order=True)
class YearMonth:
    year: int
    month: int

    @property
    def index(self) -> int:
        """Months since year 0, for counting."""
        return self.year * 12 + self.month - 1

    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


@dataclass(frozen=True, slots=True)
class Period:
    start: YearMonth
    end: YearMonth | None  # None means "present"

    def end_at(self, today: date) -> YearMonth:
        return self.end or YearMonth(today.year, today.month)

    @property
    def years(self) -> frozenset[int]:
        """The calendar years named by the period. "present" names no year."""
        return frozenset({self.start.year} | ({self.end.year} if self.end else set()))

    def __str__(self) -> str:
        return f"{self.start} to {self.end or 'present'}"


@dataclass(frozen=True, slots=True)
class Fact:
    """One thing that may be claimed about the person. Documents and assessments point at it by id."""

    id: str
    kind: FactKind
    text: str
    org: str | None = None
    role: str | None = None
    period: Period | None = None
    skills: tuple[str, ...] = ()

    @property
    def skill_names(self) -> frozenset[str]:
        return canonical_set(self.skills)


@dataclass(frozen=True, slots=True)
class Location:
    city: str | None
    country: str | None


@dataclass(frozen=True, slots=True)
class Language:
    code: str
    level: str | None = None


@dataclass(frozen=True, slots=True)
class Person:
    name: str
    headline: str | None
    email: str | None
    phone: str | None
    links: tuple[str, ...]
    location: Location | None
    languages: tuple[Language, ...]
    work_authorization: frozenset[str]

    def __repr__(self) -> str:
        # Contact details stay out of logs and error messages.
        return "Person(***)"


@dataclass(frozen=True, slots=True)
class Limits:
    """What the person will not accept. Empty lists mean "anything"."""

    countries: frozenset[str] = frozenset()
    remote: bool = True
    relocation: bool = True
    employment: frozenset[str] = frozenset()
    years_gap_allowed: int = 2
    exclude_companies: tuple[str, ...] = ()
    title_keywords: tuple[str, ...] = ()
    title_exclude: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Style:
    metrics: bool = True


@dataclass(frozen=True, slots=True)
class Career:
    person: Person
    limits: Limits
    style: Style
    facts: tuple[Fact, ...]

    def fact(self, fact_id: str) -> Fact | None:
        return next((f for f in self.facts if f.id == fact_id), None)

    @property
    def fact_ids(self) -> frozenset[str]:
        return frozenset(f.id for f in self.facts)

    @property
    def skills(self) -> frozenset[str]:
        """Every skill of the person, as canonical names."""
        return frozenset(name for f in self.facts for name in f.skill_names)

    @property
    def skill_spellings(self) -> tuple[str, ...]:
        """The skills as the person wrote them, first spelling of each, in file order."""
        seen: dict[str, str] = {}
        for f in self.facts:
            for skill in f.skills:
                seen.setdefault(canonical(skill), skill)
        return tuple(seen.values())

    @property
    def organizations(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(f.org for f in self.facts if f.org))

    def facts_with_skill(self, name: str) -> tuple[Fact, ...]:
        wanted = canonical(name)
        return tuple(f for f in self.facts if wanted in f.skill_names)

    def months_of_experience(self, today: date) -> int:
        """The months covered by experience periods up to today, counted once where they overlap."""
        now = YearMonth(today.year, today.month).index
        covered: set[int] = set()
        for f in self.facts:
            if f.kind is FactKind.EXPERIENCE and f.period is not None:
                covered.update(range(f.period.start.index, min(f.period.end_at(today).index, now) + 1))
        return len(covered)

    def years_of_experience(self, today: date) -> float:
        return self.months_of_experience(today) / 12


def checksum(content: bytes) -> str:
    """The identity of a career file's content. Stored with every result made from it."""
    return hashlib.sha256(content).hexdigest()


_KINDS = {k.value for k in FactKind}
_EMPLOYMENT = frozenset({"full-time", "part-time", "contract", "internship"})
_TOP_KEYS = {"person", "limits", "style", "facts"}
_PERSON_KEYS = {"name", "headline", "email", "phone", "links", "location", "languages", "work_authorization"}
_LIMIT_KEYS = {
    "countries",
    "remote",
    "relocation",
    "employment",
    "years_gap_allowed",
    "exclude_companies",
    "title_keywords",
    "title_exclude",
}
_FACT_KEYS = {"id", "kind", "text", "org", "role", "period", "skills"}


class _Reader:
    """Collects findings while the file is read, so one run reports every fault."""

    def __init__(self) -> None:
        self.findings: list[Finding] = []

    def error(self, code: str, path: str, message: str) -> None:
        self.findings.append(Finding.error(code, path, message))

    def warn(self, code: str, path: str, message: str) -> None:
        self.findings.append(Finding.warning(code, path, message))

    def keys(self, data: Mapping[str, Any], allowed: set[str], path: str) -> None:
        for key in data:
            if key not in allowed:
                where = f"{path}.{key}" if path else str(key)
                self.error("CAREER-FIELD", where, f"unknown field; allowed here: {', '.join(sorted(allowed))}")

    def mapping(self, value: Any, path: str) -> Mapping[str, Any]:
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return value
        self.error("CAREER-FIELD", path, "must be a mapping of fields")
        return {}

    def text(self, value: Any, path: str, *, required: bool = False) -> str | None:
        if value is None or value == "":
            if required:
                self.error("CAREER-FIELD", path, "is required")
            return None
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        self.error("CAREER-FIELD", path, "must be text")
        return None

    def flag(self, value: Any, path: str, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        self.error("CAREER-FIELD", path, "must be true or false")
        return default

    def texts(self, value: Any, path: str) -> tuple[str, ...]:
        if value is None:
            return ()
        if not isinstance(value, list):
            self.error("CAREER-FIELD", path, "must be a list")
            return ()
        items = [self.text(item, f"{path}[{i}]") for i, item in enumerate(value)]
        return tuple(item for item in items if item)

    def countries(self, value: Any, path: str) -> frozenset[str]:
        codes = self.texts(value, path)
        for i, code in enumerate(codes):
            if not _COUNTRY.match(code):
                self.error(
                    "CAREER-CODE", f"{path}[{i}]", f"'{code}' is not a country code of two capital letters, such as SA"
                )
        return frozenset(c for c in codes if _COUNTRY.match(c))


def parse_career(data: Any) -> Result[Career]:
    """Reads the loaded YAML of a career file. Every broken rule is reported with its path."""
    r = _Reader()
    if not isinstance(data, Mapping):
        return Result(
            None,
            (Finding.error("CAREER-FIELD", "", "the file must be a mapping with person, limits, style and facts"),),
        )
    r.keys(data, _TOP_KEYS, "")

    person = _person(r, r.mapping(data.get("person"), "person"))
    limits = _limits(r, r.mapping(data.get("limits"), "limits"))
    style_data = r.mapping(data.get("style"), "style")
    r.keys(style_data, {"metrics"}, "style")
    style = Style(metrics=r.flag(style_data.get("metrics"), "style.metrics", True))
    facts = _facts(r, data.get("facts"))

    if any(f.severity == "error" for f in r.findings) or person is None:
        return Result(None, tuple(r.findings))

    for fact in facts:
        if not fact.skills and fact.kind in (FactKind.EXPERIENCE, FactKind.PROJECT, FactKind.SKILL):
            r.warn(
                "CAREER-NO-SKILLS",
                f"facts.{fact.id}",
                "has no skills, so it cannot support a requirement that names a technology",
            )
        if style.metrics and fact.kind is FactKind.EXPERIENCE and not re.search(r"\d", fact.text):
            r.warn(
                "CAREER-NO-NUMBERS",
                f"facts.{fact.id}",
                "has no number; a result with a number is stronger, when you have one",
            )
    if len(facts) < 3:
        r.warn("CAREER-THIN", "facts", "fewer than three facts: most requirements will find no evidence")
    return Result(Career(person, limits, style, tuple(facts)), tuple(r.findings))


def _person(r: _Reader, data: Mapping[str, Any]) -> Person | None:
    r.keys(data, _PERSON_KEYS, "person")
    name = r.text(data.get("name"), "person.name", required=True)
    location_data = r.mapping(data.get("location"), "person.location")
    r.keys(location_data, {"city", "country"}, "person.location")
    country = r.text(location_data.get("country"), "person.location.country")
    if country is not None and not _COUNTRY.match(country):
        r.error(
            "CAREER-CODE",
            "person.location.country",
            f"'{country}' is not a country code of two capital letters, such as EG",
        )
    languages: list[Language] = []
    raw_languages = data.get("languages")
    if raw_languages is not None and not isinstance(raw_languages, list):
        r.error("CAREER-FIELD", "person.languages", "must be a list")
        raw_languages = []
    for i, item in enumerate(raw_languages or []):
        path = f"person.languages[{i}]"
        entry = r.mapping(item if not isinstance(item, str) else {"code": item}, path)
        r.keys(entry, {"code", "level"}, path)
        code = r.text(entry.get("code"), f"{path}.code", required=True)
        if code is None:
            continue
        if not _LANGUAGE.match(code):
            r.error("CAREER-CODE", f"{path}.code", f"'{code}' is not a language code of two small letters, such as ar")
            continue
        languages.append(Language(code, r.text(entry.get("level"), f"{path}.level")))
    if name is None:
        return None
    return Person(
        name=name,
        headline=r.text(data.get("headline"), "person.headline"),
        email=r.text(data.get("email"), "person.email"),
        phone=r.text(data.get("phone"), "person.phone"),
        links=r.texts(data.get("links"), "person.links"),
        location=Location(r.text(location_data.get("city"), "person.location.city"), country)
        if location_data
        else None,
        languages=tuple(languages),
        work_authorization=r.countries(data.get("work_authorization"), "person.work_authorization"),
    )


def _limits(r: _Reader, data: Mapping[str, Any]) -> Limits:
    r.keys(data, _LIMIT_KEYS, "limits")
    employment = r.texts(data.get("employment"), "limits.employment")
    for i, kind in enumerate(employment):
        if kind not in _EMPLOYMENT:
            r.error(
                "CAREER-FIELD", f"limits.employment[{i}]", f"'{kind}' is not one of: {', '.join(sorted(_EMPLOYMENT))}"
            )
    gap = data.get("years_gap_allowed", 2)
    if not isinstance(gap, int) or isinstance(gap, bool) or not 0 <= gap <= 20:
        r.error("CAREER-FIELD", "limits.years_gap_allowed", "must be a whole number from 0 to 20")
        gap = 2
    return Limits(
        countries=r.countries(data.get("countries"), "limits.countries"),
        remote=r.flag(data.get("remote"), "limits.remote", True),
        relocation=r.flag(data.get("relocation"), "limits.relocation", True),
        employment=frozenset(e for e in employment if e in _EMPLOYMENT),
        years_gap_allowed=gap,
        exclude_companies=r.texts(data.get("exclude_companies"), "limits.exclude_companies"),
        title_keywords=r.texts(data.get("title_keywords"), "limits.title_keywords"),
        title_exclude=r.texts(data.get("title_exclude"), "limits.title_exclude"),
    )


def _facts(r: _Reader, raw: Any) -> list[Fact]:
    if not isinstance(raw, list) or not raw:
        r.error("CAREER-EMPTY", "facts", "at least one fact is needed")
        return []
    facts: list[Fact] = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        data = r.mapping(item, f"facts[{i}]")
        if not data:
            if item is None or not isinstance(item, Mapping):
                r.error("CAREER-FIELD", f"facts[{i}]", "a fact is a mapping with id, kind and text")
            continue
        fact_id = r.text(data.get("id"), f"facts[{i}].id", required=True)
        path = f"facts.{fact_id}" if fact_id else f"facts[{i}]"
        r.keys(data, _FACT_KEYS, path)
        if fact_id is not None:
            if not _ID.match(fact_id):
                r.error(
                    "CAREER-ID",
                    f"facts[{i}].id",
                    f"'{fact_id}' must be 2 to 40 small letters, digits or '-', such as acme-search",
                )
            elif fact_id in seen:
                r.error("CAREER-ID", f"facts[{i}].id", f"'{fact_id}' is used by an earlier fact")
            seen.add(fact_id)
        kind_text = r.text(data.get("kind"), f"{path}.kind", required=True)
        if kind_text is not None and kind_text not in _KINDS:
            r.error("CAREER-FIELD", f"{path}.kind", f"'{kind_text}' is not one of: {', '.join(sorted(_KINDS))}")
            kind_text = None
        text = r.text(data.get("text"), f"{path}.text", required=True)
        if text is not None and not MIN_TEXT <= len(text) <= MAX_TEXT:
            r.error("CAREER-TEXT", f"{path}.text", f"must have {MIN_TEXT} to {MAX_TEXT} characters; it has {len(text)}")
        org = r.text(data.get("org"), f"{path}.org")
        role = r.text(data.get("role"), f"{path}.role")
        period = _period(r, data.get("period"), f"{path}.period")
        if kind_text == FactKind.EXPERIENCE and (org is None or role is None or period is None):
            r.error("CAREER-EXPERIENCE", path, "an experience needs org, role and period")
        if fact_id is None or kind_text is None or text is None:
            continue
        facts.append(
            Fact(fact_id, FactKind(kind_text), text, org, role, period, r.texts(data.get("skills"), f"{path}.skills"))
        )
    return facts


def _period(r: _Reader, raw: Any, path: str) -> Period | None:
    if raw is None:
        return None
    data = r.mapping(raw, path)
    if not data:
        return None
    r.keys(data, {"from", "to"}, path)
    start = _year_month(r, data.get("from"), f"{path}.from")
    end_raw = data.get("to", "present")
    end = None if end_raw in ("present", None) else _year_month(r, end_raw, f"{path}.to")
    if start is None or (end_raw not in ("present", None) and end is None):
        return None
    if end is not None and end < start:
        r.error("CAREER-PERIOD", path, f"ends ({end}) before it starts ({start})")
        return None
    return Period(start, end)


def _year_month(r: _Reader, raw: Any, path: str) -> YearMonth | None:
    match = _YEAR_MONTH.match(raw) if isinstance(raw, str) else None
    if match is None or not 1 <= int(match.group(2)) <= 12:
        r.error(
            "CAREER-PERIOD",
            path,
            f"'{raw}' is not a month written as YYYY-MM, such as 2024-03 (in quotes), or 'present'",
        )
        return None
    return YearMonth(int(match.group(1)), int(match.group(2)))
