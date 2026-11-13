from __future__ import annotations

from masar.domain.claims import Block, BlockKind, DocumentKind, Section, Violation
from masar.domain.document import assemble
from tests.support.career import career_with, example_career
from tests.support.jobs import example_job


def bullet(fact: str, text: str) -> Block:
    return Block(Section.EXPERIENCE, BlockKind.CLAIM, text, (fact,), fact)


def body(text: str, *facts: str) -> Block:
    return Block(Section.BODY, BlockKind.CLAIM if facts else BlockKind.PLAIN, text, facts)


CV_BLOCKS = (
    Block(Section.SUMMARY, BlockKind.CLAIM, "Backend engineer who builds event-driven services.", ("acme-allocation",)),
    Block(Section.SUMMARY, BlockKind.CLAIM, "Comfortable from API design to operations.", ("nimbus-apis", "tooling")),
    bullet("acme-allocation", "Built the allocation service on Kafka."),
    bullet("acme-allocation", "Raised store availability to 93%."),
    bullet("nimbus-apis", "Kept listing APIs fast and correct."),
    Block(
        Section.PROJECT, BlockKind.CLAIM, "Wrote an idempotent ledger in Java.", ("ledger-project",), "ledger-project"
    ),
)


def test_a_cv_is_built_by_code_around_the_blocks() -> None:
    document = assemble(DocumentKind.CV, "en", CV_BLOCKS, [], example_career(), example_job()).unwrap()

    assert (
        document.markdown
        == """# Sara Al-Najjar

Backend engineer

sara@example.com · +20 100 000 0000 · https://github.com/sara-example · Cairo, EG

## Summary

Backend engineer who builds event-driven services. Comfortable from API design to operations.

## Experience

### Software Engineer — Acme Retail

2023-03 – present

- Built the allocation service on Kafka.
- Raised store availability to 93%.
- Built a receiving queue over WhatsApp with OCR of delivery notes, cutting driver check-in time by 80%.
- Built a multi-agent customer support assistant that answers order questions and hands over to people when unsure.

### Backend Engineer — Nimbus Commerce

2021-06 – 2023-02

- Kept listing APIs fast and correct.
- Integrated Stripe and PayPal for stores in 4 currencies.

## Projects

- Wrote an idempotent ledger in Java.

## Education

- BSc in Computer Science — Cairo University, 2017-09 – 2021-06

## Skills

Kafka, PostgreSQL, Node.js, Python, NestJS, TypeScript, Redis, BullMQ, OCR, OpenAI, LangGraph, LangChain, FastAPI, GraphQL, REST, gRPC, MySQL, Stripe, PayPal, Java, Spring Boot, Docker, Git, Linux, GitHub Actions, AWS, Datadog

## Languages

Arabic (native), English (professional)
"""
    )
    assert document.blocks == CV_BLOCKS
    assert document.dropped == ()


def test_the_jobs_skills_come_first_in_the_skills_list() -> None:
    document = assemble(DocumentKind.CV, "en", (), [], example_career(), example_job()).unwrap()

    skills = document.markdown.split("## Skills\n\n")[1].split("\n")[0].split(", ")
    assert skills[:4] == ["Kafka", "PostgreSQL", "Node.js", "Python"]


def test_a_block_with_a_violation_is_left_out_and_listed() -> None:
    violations = [
        Violation("UNSUPPORTED_SKILL", 2, "Kubernetes"),
        Violation("TOO_LONG", 2, "300 characters; at most 240"),
        Violation("UNSUPPORTED_NUMBER", 3, "99"),
    ]

    document = assemble(DocumentKind.CV, "en", CV_BLOCKS, violations, example_career(), example_job()).unwrap()

    assert "Built the allocation service on Kafka." not in document.markdown
    assert "Raised store availability to 93%." not in document.markdown
    # No bullet of the fact is left, so its own words stand in: they are true by definition.
    assert (
        "- Built an event-driven inventory allocation service that raised store availability to 93%."
        in document.markdown
    )
    assert [(d.text, d.reasons) for d in document.dropped] == [
        (
            "Built the allocation service on Kafka.",
            ("UNSUPPORTED_SKILL: Kubernetes", "TOO_LONG: 300 characters; at most 240"),
        ),
        ("Raised store availability to 93%.", ("UNSUPPORTED_NUMBER: 99",)),
    ]
    assert len(document.blocks) == 4


def test_a_cv_with_no_blocks_is_the_career_file_as_written() -> None:
    document = assemble(DocumentKind.CV, "en", (), [], example_career(), example_job()).unwrap()

    assert "## Summary" not in document.markdown
    assert "- Maintained GraphQL and REST APIs for product listings and moved hot paths to gRPC." in document.markdown
    assert "- Wrote an open-source double-entry ledger service" in document.markdown


def test_contacts_come_only_from_the_career_file() -> None:
    sparse = career_with(
        person={"email": None, "phone": None, "links": [], "location": None, "headline": None, "languages": []}
    )

    document = assemble(DocumentKind.CV, "en", CV_BLOCKS, [], sparse, example_job()).unwrap()

    assert document.markdown.startswith("# Sara Al-Najjar\n\n## Summary")
    assert "## Languages" not in document.markdown


def test_an_arabic_cv_has_arabic_headings() -> None:
    document = assemble(
        DocumentKind.CV,
        "ar",
        (bullet("acme-allocation", "بنيت خدمة توزيع المخزون باستخدام Kafka."),),
        [],
        example_career(),
        example_job(),
    ).unwrap()

    for heading in ("## الخبرة العملية", "## المشاريع", "## التعليم", "## المهارات", "## اللغات"):
        assert heading in document.markdown
    assert "2023-03 – حتى الآن" in document.markdown
    assert "العربية (native), الإنجليزية (professional)" in document.markdown
    assert document.language == "ar"


LETTER = (
    body("Your work on parcel logistics caught my attention."),
    body("At Acme Retail I built an event-driven allocation service on Kafka.", "acme-allocation"),
    body("I would be glad to talk."),
)


def test_a_cover_letter_gets_its_greeting_and_signature_from_code() -> None:
    document = assemble(DocumentKind.COVER, "en", LETTER, [], example_career(), example_job()).unwrap()

    assert (
        document.markdown
        == """Dear Tamween team,

Your work on parcel logistics caught my attention.

At Acme Retail I built an event-driven allocation service on Kafka.

I would be glad to talk.

Sincerely,
Sara Al-Najjar
sara@example.com · +20 100 000 0000
"""
    )


def test_an_outreach_message_is_short_and_signed() -> None:
    document = assemble(DocumentKind.OUTREACH, "ar", LETTER[1:2], [], example_career(), example_job()).unwrap()

    assert document.markdown == "مرحبًا فريق Tamween،\n\n" + LETTER[1].text + "\n\n— Sara Al-Najjar\n"


def test_a_letter_with_too_few_paragraphs_left_is_a_failed_draft() -> None:
    violations = [Violation("UNSUPPORTED_SKILL", 1, "Kubernetes"), Violation("PLAIN_BLOCK_CLAIMS", 2, "x")]

    cover = assemble(DocumentKind.COVER, "en", LETTER, violations, example_career(), example_job())
    outreach = assemble(DocumentKind.OUTREACH, "en", LETTER, violations, example_career(), example_job())
    nothing = assemble(
        DocumentKind.OUTREACH, "en", LETTER, [Violation("X", i, "x") for i in range(3)], example_career(), example_job()
    )

    assert cover.value is None
    assert cover.errors[0].code == "DOCUMENT-TOO-SHORT"
    assert outreach.ok
    assert nothing.errors[0].message == "only 0 of the needed 1 paragraphs passed the checks"


def test_a_violation_that_points_outside_the_draft_is_ignored() -> None:
    document = assemble(
        DocumentKind.COVER,
        "en",
        LETTER,
        [Violation("X", 9, "x"), Violation("Y", -1, "y")],
        example_career(),
        example_job(),
    ).unwrap()

    assert len(document.blocks) == 3
    assert document.dropped == ()


def test_a_company_name_from_a_posting_cannot_bring_markup_into_a_letter() -> None:
    job = example_job(company="[Evil](https://evil.test) <b>Co</b>")
    blocks = (
        Block(Section.BODY, BlockKind.PLAIN, "I am writing about the role."),
        Block(Section.BODY, BlockKind.CLAIM, "I built an allocation service on Kafka.", ("acme-allocation",)),
    )
    document = assemble(DocumentKind.COVER, "en", blocks, [], example_career(), job).unwrap()
    first = document.markdown.splitlines()[0]
    assert first == "Dear Evil https evil.test b Co /b team,"
    assert "](" not in document.markdown
    assert "<b>" not in document.markdown
