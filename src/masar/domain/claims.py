"""The claim checks: no sentence about the person may stay in a document without a fact behind it (ADR-0002).

A model writes a document as blocks. A block names the facts it rests on. ``check_block`` compares the
text with those facts: every skill, product-like name, number, employer and seniority word must come
from them. What these checks cannot see is said in docs/lld/grounding.md.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from functools import cached_property
from typing import Any

from masar.domain.career import Career, Fact, FactKind
from masar.domain.findings import Finding, Result
from masar.domain.job import Job
from masar.domain.skills import SkillLexicon
from masar.domain.text import arabic_share, normalize, western_digits


class DocumentKind(StrEnum):
    CV = "cv"
    COVER = "cover"
    OUTREACH = "outreach"


class Section(StrEnum):
    SUMMARY = "summary"
    EXPERIENCE = "experience"
    PROJECT = "project"
    BODY = "body"


class BlockKind(StrEnum):
    CLAIM = "claim"
    PLAIN = "plain"


@dataclass(frozen=True, slots=True)
class Block:
    """One sentence, bullet or paragraph of a draft, with the facts it rests on."""

    section: Section
    kind: BlockKind
    text: str
    facts: tuple[str, ...] = ()
    fact: str | None = None  # for experience and project bullets: the fact the bullet belongs to

    @property
    def is_claim(self) -> bool:
        # Everything in a CV says something about the person. Only a letter has room for a sentence that does not.
        return self.kind is BlockKind.CLAIM or self.section is not Section.BODY


@dataclass(frozen=True, slots=True)
class Violation:
    """Why a block may not stay. ``block`` is its position in the draft."""

    code: str
    block: int
    detail: str


# Limits, per place.
MAX_BULLET = 240
MAX_PARAGRAPH = 700
MAX_SUMMARY_BLOCKS = 3
MAX_BULLETS_PER_FACT = 4
BODY_BLOCKS = {DocumentKind.COVER: (2, 6), DocumentKind.OUTREACH: (1, 4)}
BODY_TOTAL = {DocumentKind.COVER: 1800, DocumentKind.OUTREACH: 700}

_SECTIONS = {
    DocumentKind.CV: {Section.SUMMARY, Section.EXPERIENCE, Section.PROJECT},
    DocumentKind.COVER: {Section.BODY},
    DocumentKind.OUTREACH: {Section.BODY},
}

# Words that claim rank or ownership. Each is looked for as a whole word.
_TITLE_WORDS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in (
        ("senior", r"\bsenior\b"),
        ("principal", r"\bprincipal\b"),
        (
            "lead",
            r"\b(?:tech(?:nical)?|team|engineering)\s+lead\b|\blead\s+(?:engineer|developer|architect|designer)\b",
        ),
        ("led", r"\bled\b"),
        ("head of", r"\bhead\s+of\b"),
        ("manager", r"\bmanager\b"),
        ("managed", r"\bmanaged\b"),
        ("director", r"\bdirector\b"),
        ("architect", r"\barchitect(?:ed)?\b"),
        ("expert", r"\bexpert\b"),
        ("chief", r"\bchief\b"),
        ("founder", r"\b(?:co-?)?founder\b"),
        ("قائد", r"(?<![ء-ي])قائد(?![ء-ي])"),
        ("قدت", r"(?<![ء-ي])قدت(?![ء-ي])"),
        ("أدرت", r"(?<![ء-ي])أدرت(?![ء-ي])"),
        ("مدير", r"(?<![ء-ي])مدير(?![ء-ي])"),
        ("خبير", r"(?<![ء-ي])خبير(?![ء-ي])"),
        ("كبير", r"(?<![ء-ي])كبير(?![ء-ي])"),
    )
)

# Everyday short forms that look like product names and are not.
_PLAIN_TERMS = frozenset(
    [
        "cv",
        "ok",
        "ps",
        "api",
        "apis",
        "sdk",
        "sdks",
        "ui",
        "ux",
        "qa",
        "it",
        "saas",
        "b2b",
        "b2c",
        "kpi",
        "kpis",
        "sla",
        "slas",
        "mvp",
        "ceo",
        "cto",
        "hr",
        "id",
        "ids",
        "url",
        "urls",
        "http",
        "https",
        "json",
        "csv",
        "pdf",
        "ksa",
        "uae",
        "usa",
        "uk",
        "eu",
        "us",
        "gcc",
        "mena",
        "faq",
        "faqs",
        "am",
        "pm",
    ]
)

# A token for names: letters, digits and the symbols names carry. "-" and "/" split tokens ("AI-powered", "TCP/IP").
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+#_]*")
# A number may carry a unit ("3x", "200ms", "10k"). Digits inside a word ("S3", "EC2") are not numbers.
_NUMBER = re.compile(r"(?<![A-Za-z0-9_.])\d+(?:[.,]\d+)*(?:\s?[kKmM](?![A-Za-z]))?(?![0-9_])")
_NUMBER_WORD = re.compile(r"\b(dozens?|decades?|hundreds?|thousands?|millions?|billions?)\b", re.IGNORECASE)
_YEAR_WORDS = ("two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen")
_WORD_VALUES = {word: value for value, word in enumerate(_YEAR_WORDS, start=2)}
_YEARS_IN_WORDS = re.compile(rf"\b({'|'.join(_YEAR_WORDS)})\s+(?:\w+\s+)?years?\b", re.IGNORECASE)
_URL = re.compile(r"https?://|www\.|\b[\w.+-]+@[\w-]+\.[\w.]+\b", re.IGNORECASE)
_HTML = re.compile(r"<[A-Za-z/!][^>]*>")
_MARKDOWN_START = re.compile(r"^\s*(?:#{1,6}\s|[-*+>]\s|\d+[.)]\s|\|)")
_PLACEHOLDER = re.compile(
    r"\[[^\]\n]{1,60}\]|\{[^}\n]{1,60}\}|\bX{3,}\b|\byour name\b|\blorem ipsum\b|\bTODO\b|\bTBD\b", re.IGNORECASE
)


@dataclass(frozen=True)
class ClaimContext:
    """Everything the checks compare a block against."""

    career: Career
    today: date
    language: str = "en"
    job: Job | None = None
    posting_text: str = ""
    extra_skills: tuple[str, ...] = field(default=())

    @cached_property
    def lexicon(self) -> SkillLexicon:
        job_skills = self.job.skills if self.job else ()
        return SkillLexicon((*self.career.skill_spellings, *job_skills, *self.extra_skills))

    @cached_property
    def years(self) -> int:
        """The person's whole years of experience: a number any block may state."""
        return int(self.career.years_of_experience(self.today))

    @cached_property
    def posting_numbers(self) -> frozenset[str]:
        return _numbers(self.posting_text, ())

    @cached_property
    def posting_tokens(self) -> frozenset[str]:
        return frozenset(_term_key(t) for t in _TOKEN.findall(self.posting_text))

    @cached_property
    def masks(self) -> tuple[re.Pattern[str], ...]:
        """The job's own title and company: naming the role is not a claim about the person."""
        names = [self.job.title, self.job.company] if self.job else []
        return tuple(_phrase(name) for name in names if name.strip())


def parse_blocks(raw: Any) -> Result[tuple[Block, ...]]:
    """Reads the blocks a model wrote. A block that is not even a block is an error for the whole draft."""
    entries = raw.get("blocks") if isinstance(raw, Mapping) else raw
    if not isinstance(entries, list) or not entries:
        return Result(None, (Finding.error("BLOCKS-SHAPE", "blocks", "a draft is a list of blocks"),))
    blocks: list[Block] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, Mapping) or not isinstance(entry.get("text"), str):
            return Result(
                None, (Finding.error("BLOCKS-SHAPE", f"blocks[{i}]", "a block needs text, section, kind and facts"),)
            )
        section = str(entry.get("section", "")).strip().casefold()
        kind = str(entry.get("kind", "claim")).strip().casefold()
        if section not in {s.value for s in Section}:
            return Result(
                None, (Finding.error("BLOCKS-SHAPE", f"blocks[{i}].section", f"'{section}' is not a section"),)
            )
        facts = entry.get("facts")
        fact = entry.get("fact")
        blocks.append(
            Block(
                section=Section(section),
                # Anything that is not clearly "plain" is checked as a claim: the strict reading.
                kind=BlockKind.PLAIN if kind == "plain" else BlockKind.CLAIM,
                # A leading list mark is habit, not content.
                text=re.sub(r"^\s*[-*•]\s+", "", entry["text"]).strip(),
                facts=tuple(dict.fromkeys(f for f in (facts if isinstance(facts, list) else []) if isinstance(f, str))),
                fact=fact if isinstance(fact, str) and fact else None,
            )
        )
    return Result(tuple(blocks))


def check_document(kind: DocumentKind, blocks: Iterable[Block], context: ClaimContext) -> list[Violation]:
    """Every violation of every block, then the limits of the document as a whole."""
    blocks = tuple(blocks)
    violations: list[Violation] = []
    for index, block in enumerate(blocks):
        if block.section not in _SECTIONS[kind]:
            violations.append(Violation("WRONG_SECTION", index, f"a {kind.value} has no {block.section.value} section"))
            continue
        violations += check_block(block, index, context)

    # Too many of a kind: the extra ones go, in the order they were written.
    summary = [i for i, b in enumerate(blocks) if b.section is Section.SUMMARY]
    violations += [
        Violation("TOO_LONG", i, f"at most {MAX_SUMMARY_BLOCKS} summary blocks") for i in summary[MAX_SUMMARY_BLOCKS:]
    ]
    per_fact: dict[str, int] = {}
    for i, b in enumerate(blocks):
        if b.section in (Section.EXPERIENCE, Section.PROJECT) and b.fact:
            per_fact[b.fact] = per_fact.get(b.fact, 0) + 1
            if per_fact[b.fact] > MAX_BULLETS_PER_FACT:
                violations.append(Violation("TOO_LONG", i, f"at most {MAX_BULLETS_PER_FACT} bullets for one fact"))
    if kind in BODY_BLOCKS:
        body = [i for i, b in enumerate(blocks) if b.section is Section.BODY]
        most = BODY_BLOCKS[kind][1]
        violations += [Violation("TOO_LONG", i, f"at most {most} paragraphs") for i in body[most:]]
        total = 0
        for i in body[:most]:
            total += len(blocks[i].text)
            if total > BODY_TOTAL[kind]:
                violations.append(Violation("TOO_LONG", i, f"the {kind.value} is over {BODY_TOTAL[kind]} characters"))
    return violations


def check_block(block: Block, index: int, context: ClaimContext) -> list[Violation]:
    """The violations of one block."""
    found: list[Violation] = []

    def add(code: str, detail: str) -> None:
        found.append(Violation(code, index, detail))

    text = block.text
    career = context.career

    # Form first: a block is one piece of plain text.
    if not text.strip():
        add("FORMAT", "empty")
        return found
    if "\n" in text or _URL.search(text) or _HTML.search(text) or _MARKDOWN_START.match(text):
        add("FORMAT", "a block is one line of plain text: no line breaks, links, HTML or list marks")
    if placeholder := _PLACEHOLDER.search(text):
        add("PLACEHOLDER", placeholder.group(0))
    limit = MAX_BULLET if block.section is not Section.BODY else MAX_PARAGRAPH
    if len(text) > limit:
        add("TOO_LONG", f"{len(text)} characters; at most {limit}")

    # The facts the block names.
    cited: list[Fact] = []
    for fact_id in block.facts:
        fact = career.fact(fact_id)
        if fact is None:
            add("UNKNOWN_FACT", fact_id)
        else:
            cited.append(fact)
    if block.section in (Section.EXPERIENCE, Section.PROJECT):
        wanted = FactKind.EXPERIENCE if block.section is Section.EXPERIENCE else FactKind.PROJECT
        own = career.fact(block.fact) if block.fact else None
        if own is None or own.kind is not wanted or block.fact not in block.facts:
            add(
                "WRONG_SECTION_FACT",
                f"a bullet under {block.section.value} must belong to one {wanted.value} fact and cite it",
            )
    if block.is_claim and not cited:
        add("CLAIM_WITHOUT_FACT", "a claim names the facts it rests on")

    # What the text says. The job's own title and company are masked: naming the role is not a claim.
    masked = text
    for mask in context.masks:
        masked = mask.sub(lambda m: " " * len(m.group(0)), masked)

    hits = context.lexicon.find(masked)
    spans = [(h.start, h.end) for h in hits]
    support = _Support(cited, context)

    if block.is_claim:
        for hit in hits:
            if hit.name not in support.skills:
                add("UNSUPPORTED_SKILL", hit.surface)
    elif hits:
        add("PLAIN_BLOCK_CLAIMS", f"names a skill: {hits[0].surface}")

    for term in _terms(masked, spans):
        key = _term_key(term)
        if block.is_claim:
            if key not in support.tokens:
                add("UNSUPPORTED_TERM", term)
        elif key not in context.posting_tokens:
            add("PLAIN_BLOCK_CLAIMS", f"names something that is not in the posting: {term}")

    numbers = _numbers(masked, spans)
    # The person's own years of experience are a number code computed itself, but only when said as years:
    # "5 years" is fine for a person with five; "improved it by 5%" is a number like any other.
    allowed_always = {str(context.years)} if context.years > 0 and _states_years(masked, context.years) else set()
    for number in sorted(numbers):
        if block.is_claim:
            if number in allowed_always:
                continue
            if not career.style.metrics:
                add("NUMBERS_NOT_WANTED", number)
            elif number not in support.numbers:
                add("UNSUPPORTED_NUMBER", number)
        elif number not in context.posting_numbers:
            add("PLAIN_BLOCK_CLAIMS", f"states a number that is not in the posting: {number}")

    said = normalize(masked)
    for org in career.organizations:
        if _phrase(org).search(said):
            if not block.is_claim:
                add("PLAIN_BLOCK_CLAIMS", f"names your employer: {org}")
            elif normalize(org) not in support.orgs:
                add("UNSUPPORTED_ORG", org)

    for name, pattern in _TITLE_WORDS:
        if pattern.search(masked):
            if not block.is_claim:
                add("PLAIN_BLOCK_CLAIMS", f"uses a word of rank: {name}")
            elif not pattern.search(support.text):
                add("UNSUPPORTED_TITLE", name)

    # Language: the letters that are not names of technologies decide.
    letters = _blank(masked, spans)
    letters = " ".join(t for t in letters.split() if not _is_product_like(t.strip(".,;:()")))
    share = arabic_share(letters)
    if context.language == "ar" and share < 0.5:
        add("WRONG_LANGUAGE", "an Arabic document needs Arabic sentences; names of technologies stay as they are")
    if context.language != "ar" and share > 0.2:
        add("WRONG_LANGUAGE", "this document is not in Arabic")
    return found


class _Support:
    """What the cited facts say, in the forms the checks compare with."""

    def __init__(self, facts: list[Fact], context: ClaimContext) -> None:
        self.text = " \n ".join(" ".join(filter(None, (f.text, f.role, f.org))) for f in facts)
        self.skills = {name for f in facts for name in f.skill_names} | context.lexicon.names_in(self.text)
        self.tokens = {_term_key(t) for t in _TOKEN.findall(self.text)} | {
            _term_key(t) for f in facts for s in f.skills for t in _TOKEN.findall(s)
        }
        self.numbers = _numbers(self.text, ()) | {str(year) for f in facts if f.period for year in f.period.years}
        self.orgs = {normalize(f.org) for f in facts if f.org}


def _phrase(words: str) -> re.Pattern[str]:
    body = r"\s+".join(re.escape(part) for part in words.split())
    return re.compile(rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])", re.IGNORECASE)


def _blank(text: str, spans: Iterable[tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in spans:
        chars[start:end] = " " * (end - start)
    return "".join(chars)


def _is_product_like(token: str) -> bool:
    """True for a token written like the name of a product or a technology."""
    token = token.rstrip(".-/_")
    letters = [c for c in token if c.isalpha()]
    if len(letters) < 2 and not (letters and any(c.isdigit() for c in token)):
        return False
    if token.casefold() in _PLAIN_TERMS:
        return False
    if token.isdigit() or not letters:
        return False
    all_caps = all(c.isupper() for c in letters)
    if all_caps and 2 <= len(token) <= 6 and len(letters) >= 2:
        return True  # AWS, ETL
    if any(c.isupper() for c in token[1:]) and any(c.islower() for c in token):
        return True  # GraphQL, gRPC, OpenAI
    if any(c.isdigit() for c in token) and letters:
        return True  # OAuth2, EC2
    if re.fullmatch(r"[A-Za-z]{2,}\.[A-Za-z]{2,}", token):
        return True  # Next.js, socket.io
    return token.endswith(("++", "#"))


def _terms(text: str, skill_spans: Iterable[tuple[int, int]]) -> list[str]:
    """Product-like names in a text, outside the skills already found, each once."""
    seen: dict[str, str] = {}
    for token in _TOKEN.findall(_blank(text, skill_spans)):
        token = token.rstrip(".-/_")
        if token and _is_product_like(token):
            seen.setdefault(_term_key(token), token)
    return list(seen.values())


def _term_key(token: str) -> str:
    token = token.rstrip(".-/_").casefold()
    # "APIs" and "API" are the same name.
    return token[:-1] if len(token) > 3 and token.endswith("s") and not token.endswith("ss") else token


def _states_years(text: str, years: int) -> bool:
    """True when the text says this number as an amount of years: "5 years", "5+ years of", "five years", "5 سنوات"."""
    plain = western_digits(text)
    in_digits = re.search(
        rf"(?<![\d.,]){years}\+?\s*(?:\w+\s+){{0,2}}(?:years?\b|سنوات|سنة|أعوام|عام)", plain, re.IGNORECASE
    )
    in_words = any(_WORD_VALUES[m.group(1).casefold()] == years for m in _YEARS_IN_WORDS.finditer(plain))
    return in_digits is not None or in_words


def _numbers(text: str, skill_spans: Iterable[tuple[int, int]]) -> frozenset[str]:
    """The numbers a text states, in one form: digits only, "10k" as 10000, number words as words."""
    plain = western_digits(_blank(text, skill_spans))
    found: set[str] = set()
    for match in _NUMBER.finditer(plain):
        raw = match.group(0).replace(" ", "")
        factor = 1
        if raw[-1] in "kK":
            factor, raw = 1_000, raw[:-1]
        elif raw[-1] in "mM":
            factor, raw = 1_000_000, raw[:-1]
        digits = raw.replace(",", "")
        try:
            value = float(digits) * factor
        except ValueError:
            continue
        found.add(str(int(value)) if value == int(value) else str(value))
    for match in _NUMBER_WORD.finditer(plain):
        found.add(match.group(1).casefold().rstrip("s"))
    for match in _YEARS_IN_WORDS.finditer(plain):
        found.add(str(_WORD_VALUES[match.group(1).casefold()]))
    return frozenset(found)
