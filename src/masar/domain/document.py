"""Building a document. Code writes everything that is not a block: the header, the contacts, the headings,
the education, the skills list, the greeting and the signature. A block that failed a check is left out and listed.
"""

from __future__ import annotations

from dataclasses import dataclass

from masar.domain.career import Career, Fact, FactKind, Period
from masar.domain.claims import BODY_BLOCKS, Block, DocumentKind, Section, Violation
from masar.domain.findings import Finding, Result
from masar.domain.job import Job
from masar.domain.languages import LANGUAGE_NAMES
from masar.domain.skills import canonical
from masar.domain.text import plain_name

_LABELS = {
    "en": {
        "summary": "Summary",
        "experience": "Experience",
        "projects": "Projects",
        "education": "Education",
        "skills": "Skills",
        "languages": "Languages",
        "present": "present",
        "dear": "Dear {company} team,",
        "hello": "Hello {company} team,",
        "sincerely": "Sincerely,",
    },
    "ar": {
        "summary": "الملخص",
        "experience": "الخبرة العملية",
        "projects": "المشاريع",
        "education": "التعليم",
        "skills": "المهارات",
        "languages": "اللغات",
        "present": "حتى الآن",
        "dear": "فريق {company} المحترم،",
        "hello": "مرحبًا فريق {company}،",
        "sincerely": "مع خالص التحية،",
    },
}


@dataclass(frozen=True, slots=True)
class DroppedBlock:
    text: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Document:
    kind: DocumentKind
    language: str
    markdown: str
    blocks: tuple[Block, ...]  # the blocks that are in the document
    dropped: tuple[DroppedBlock, ...]


def assemble(
    kind: DocumentKind, language: str, blocks: tuple[Block, ...], violations: list[Violation], career: Career, job: Job
) -> Result[Document]:
    """The document made of the blocks that passed, or the reason there is none."""
    labels = _LABELS["ar" if language == "ar" else "en"]
    bad: dict[int, list[str]] = {}
    for violation in violations:
        bad.setdefault(violation.block, []).append(f"{violation.code}: {violation.detail}")
    kept = tuple(block for i, block in enumerate(blocks) if i not in bad)
    dropped = tuple(
        DroppedBlock(blocks[i].text, tuple(reasons)) for i, reasons in sorted(bad.items()) if 0 <= i < len(blocks)
    )

    if kind is DocumentKind.CV:
        markdown = _cv(kept, career, job, labels, language)
    else:
        body = [block.text for block in kept if block.section is Section.BODY]
        least = BODY_BLOCKS[kind][0]
        if len(body) < least:
            reason = f"only {len(body)} of the needed {least} paragraphs passed the checks"
            return Result(None, (Finding.error("DOCUMENT-TOO-SHORT", "blocks", reason),))
        markdown = _letter(kind, body, career, job, labels)
    return Result(Document(kind, language, markdown, kept, dropped))


def _contacts(career: Career) -> str:
    person = career.person
    place = ", ".join(filter(None, (person.location.city, person.location.country))) if person.location else ""
    return " · ".join(filter(None, (person.email, person.phone, *person.links, place)))


def _period(period: Period | None, labels: dict[str, str]) -> str:
    if period is None:
        return ""
    return f"{period.start} – {period.end or labels['present']}"


def _cv(blocks: tuple[Block, ...], career: Career, job: Job, labels: dict[str, str], language: str) -> str:
    person = career.person
    lines: list[str] = [f"# {person.name}", ""]
    if person.headline:
        lines += [person.headline, ""]
    if contacts := _contacts(career):
        lines += [contacts, ""]

    summary = [b.text for b in blocks if b.section is Section.SUMMARY]
    if summary:
        lines += [f"## {labels['summary']}", "", " ".join(summary), ""]

    def bullets(fact: Fact) -> list[str]:
        own = [b.text for b in blocks if b.fact == fact.id and b.section in (Section.EXPERIENCE, Section.PROJECT)]
        # No bullet passed for this fact: its own words are true by definition.
        return [f"- {text}" for text in (own or [fact.text])]

    experience = [f for f in career.facts if f.kind is FactKind.EXPERIENCE]
    if experience:
        lines += [f"## {labels['experience']}", ""]
        groups: dict[tuple[str | None, str | None, Period | None], list[Fact]] = {}
        for fact in experience:
            groups.setdefault((fact.org, fact.role, fact.period), []).append(fact)

        def recency(item: tuple[tuple[str | None, str | None, Period | None], list[Fact]]) -> tuple[int, int, int]:
            period = item[0][2]
            if period is None:
                return (0, 0, 0)
            return (1 if period.end is None else 0, period.end.index if period.end else 0, period.start.index)

        for (org, role, period), facts in sorted(groups.items(), key=recency, reverse=True):
            lines += [f"### {role} — {org}", "", _period(period, labels), ""]
            for fact in facts:
                lines += bullets(fact)
            lines.append("")

    projects = [f for f in career.facts if f.kind is FactKind.PROJECT]
    if projects:
        lines += [f"## {labels['projects']}", ""]
        for fact in projects:
            lines += bullets(fact)
        lines.append("")

    education = [f for f in career.facts if f.kind is FactKind.EDUCATION]
    if education:
        lines += [f"## {labels['education']}", ""]
        for fact in education:
            tail = ", ".join(filter(None, (fact.org, _period(fact.period, labels))))
            # "BSc in Computer Science. — Cairo University" reads badly: the full stop goes when more follows.
            lines.append(f"- {fact.text.rstrip('.') if tail else fact.text}" + (f" — {tail}" if tail else ""))
        lines.append("")

    skills = career.skill_spellings
    if skills:
        wanted = {canonical(s) for s in job.skills}
        ordered = [s for s in skills if canonical(s) in wanted] + [s for s in skills if canonical(s) not in wanted]
        lines += [f"## {labels['skills']}", "", ", ".join(ordered), ""]

    if person.languages:
        names = LANGUAGE_NAMES["ar" if language == "ar" else "en"]
        spoken = [
            names.get(lang.code, lang.code) + (f" ({lang.level})" if lang.level else "") for lang in person.languages
        ]
        lines += [f"## {labels['languages']}", "", ", ".join(spoken), ""]

    return "\n".join(lines).rstrip() + "\n"


def _letter(kind: DocumentKind, body: list[str], career: Career, job: Job, labels: dict[str, str]) -> str:
    person = career.person
    # The company's name comes from a posting. It goes into the letter as a name, and as nothing else.
    greeting = labels["dear" if kind is DocumentKind.COVER else "hello"].format(company=plain_name(job.company))
    lines = [greeting, ""]
    for paragraph in body:
        lines += [paragraph, ""]
    if kind is DocumentKind.COVER:
        lines += [labels["sincerely"], person.name]
        if contact := " · ".join(filter(None, (person.email, person.phone))):
            lines.append(contact)
    else:
        lines.append(f"— {person.name}")
    return "\n".join(lines).rstrip() + "\n"
