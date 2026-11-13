from __future__ import annotations

import random
import re
from typing import Any

import pytest

from masar.domain.claims import (
    Block,
    BlockKind,
    ClaimContext,
    DocumentKind,
    Section,
    check_block,
    check_document,
    parse_blocks,
)
from tests.support.career import TODAY, career_with, example_career
from tests.support.jobs import example_job

POSTING = "Tamween moves 2 million parcels a year across KSA on our ParcelOS platform. We use Kafka and Temporal. Backend Engineer, Riyadh."


def context(language: str = "en", **career_changes: Any) -> ClaimContext:
    career = career_with(**career_changes) if career_changes else example_career()
    return ClaimContext(career, TODAY, language, example_job(), POSTING)


def claim(text: str, *facts: str, section: Section = Section.BODY, fact: str | None = None) -> Block:
    return Block(section, BlockKind.CLAIM, text, facts, fact)


def plain(text: str) -> Block:
    return Block(Section.BODY, BlockKind.PLAIN, text)


def codes(block: Block, ctx: ClaimContext | None = None) -> list[tuple[str, str]]:
    return [(v.code, v.detail) for v in check_block(block, 0, ctx or context())]


def only(block: Block, ctx: ClaimContext | None = None) -> list[str]:
    return [code for code, _ in codes(block, ctx)]


def test_an_honest_claim_passes() -> None:
    assert (
        codes(
            claim(
                "I built an event-driven inventory allocation service with NestJS, Kafka and PostgreSQL.",
                "acme-allocation",
            )
        )
        == []
    )
    assert codes(claim("At Acme Retail I raised store availability to 93%.", "acme-allocation")) == []
    assert codes(claim("I have 5 years of backend experience, most recently on Kafka.", "acme-allocation")) == []


def test_a_fact_that_does_not_exist() -> None:
    assert codes(claim("I built a ledger.", "ledger-project", "made-up")) == [("UNKNOWN_FACT", "made-up")]


def test_a_claim_needs_a_fact() -> None:
    assert only(claim("I am a strong communicator.")) == ["CLAIM_WITHOUT_FACT"]
    assert only(claim("I am a strong communicator.", "made-up")) == ["UNKNOWN_FACT", "CLAIM_WITHOUT_FACT"]


def test_a_skill_must_be_in_the_cited_facts() -> None:
    # Kubernetes is what the job asks for and the person lacks: the claim a model is most tempted to make.
    assert codes(claim("I ran Kafka on Kubernetes.", "acme-allocation")) == [("UNSUPPORTED_SKILL", "Kubernetes")]
    # The person has Python, in another fact. The block must cite it.
    assert codes(claim("I built it in Python.", "acme-allocation")) == [("UNSUPPORTED_SKILL", "Python")]
    assert codes(claim("I built it in Python.", "acme-allocation", "acme-support-agent")) == []


def test_any_spelling_of_a_cited_skill_passes() -> None:
    assert codes(claim("I used Postgres and Nest.js daily.", "acme-allocation")) == []


def test_a_skill_named_in_a_facts_text_counts() -> None:
    career: dict[str, Any] = {
        "facts": [
            {"id": "x-one", "kind": "project", "text": "Wrote a cache on top of Redis for fun.", "skills": []},
            *[],
        ]
    }

    assert codes(claim("I wrote a cache on Redis.", "x-one"), context(**career)) == []


def test_an_everyday_word_is_not_a_skill() -> None:
    assert codes(claim("I react fast and go the extra mile to express ideas at Acme Retail.", "acme-allocation")) == []


def test_a_product_like_name_must_be_in_the_cited_facts() -> None:
    assert codes(claim("I built pipelines on AWS with an ETL layer.", "tooling")) == [("UNSUPPORTED_TERM", "ETL")]
    assert codes(claim("I shipped an iOS app.", "ledger-project")) == [("UNSUPPORTED_TERM", "iOS")]
    assert codes(claim("I used socket.io for updates.", "acme-receiving")) == [("UNSUPPORTED_TERM", "socket.io")]
    assert codes(claim("I built AI-powered tools.", "acme-allocation")) == [("UNSUPPORTED_TERM", "AI")]
    # Names the fact itself uses are fine, in singular or plural.
    assert codes(claim("I maintained an API over GraphQL.", "nimbus-apis")) == []
    assert codes(claim("I read delivery notes with OCR over WhatsApp.", "acme-receiving")) == []


def test_everyday_short_forms_are_not_product_names() -> None:
    assert codes(claim("I built APIs and a small UI for the KSA market, as my CV shows.", "acme-allocation")) == []


def test_a_number_must_be_in_the_cited_facts() -> None:
    assert codes(claim("I raised availability to 99%.", "acme-allocation")) == [("UNSUPPORTED_NUMBER", "99")]
    assert codes(claim("I cut check-in time by 80%.", "acme-allocation")) == [("UNSUPPORTED_NUMBER", "80")]
    assert codes(claim("I cut check-in time by 80%.", "acme-receiving")) == []
    assert codes(claim("I made it 3x faster for 10k users.", "acme-receiving")) == [
        ("UNSUPPORTED_TERM", "3x"),
        ("UNSUPPORTED_TERM", "10k"),
        ("UNSUPPORTED_NUMBER", "10000"),
        ("UNSUPPORTED_NUMBER", "3"),
    ]


def test_numbers_in_other_forms() -> None:
    assert only(claim("رفعت التوافر إلى ٩٣٪ في Acme Retail.", "acme-allocation"), context("ar")) == []
    assert only(claim("رفعت التوافر إلى ٩٩٪.", "acme-allocation"), context("ar")) == ["UNSUPPORTED_NUMBER"]
    assert codes(claim("I supported stores in 4 currencies.", "nimbus-payments")) == []
    assert codes(claim("I supported stores in 40 currencies.", "nimbus-payments")) == [("UNSUPPORTED_NUMBER", "40")]
    assert only(claim("I served thousands of stores.", "nimbus-payments")) == ["UNSUPPORTED_NUMBER"]
    assert only(claim("I have a decade of experience.", "nimbus-apis")) == ["UNSUPPORTED_NUMBER"]
    assert only(claim("I have eight years of experience.", "nimbus-apis")) == ["UNSUPPORTED_NUMBER"]


def test_a_year_of_the_facts_period_is_a_number_of_the_fact() -> None:
    assert codes(claim("I joined in 2021 and stayed until 2023.", "nimbus-apis")) == []
    assert codes(claim("I joined in 2019.", "nimbus-apis")) == [("UNSUPPORTED_NUMBER", "2019")]


def test_the_persons_years_of_experience_may_always_be_stated() -> None:
    # 5.5 years: "5" and "5+" are true, also in words; "6" is not.
    assert codes(claim("I have 5+ years of experience.", "nimbus-apis")) == []
    assert codes(claim("I have five years of experience.", "nimbus-apis")) == []
    assert codes(claim("I have 6 years of experience.", "nimbus-apis")) == [("UNSUPPORTED_NUMBER", "6")]
    assert codes(claim("لدي 5 سنوات من الخبرة.", "nimbus-apis"), context("ar")) == []
    # The same digit as anything else than years is a number like any other.
    assert codes(claim("I made listings 5 times faster.", "nimbus-apis")) == [("UNSUPPORTED_NUMBER", "5")]
    assert codes(claim("I improved it by 5%.", "nimbus-apis")) == [("UNSUPPORTED_NUMBER", "5")]


def test_digits_inside_names_are_not_numbers() -> None:
    career: dict[str, Any] = {
        "facts": [
            {
                "id": "files",
                "kind": "project",
                "text": "Stored uploads on S3 behind OAuth2 with Python 3.",
                "skills": ["S3", "OAuth", "Python"],
            }
        ]
    }

    assert codes(claim("I stored uploads on S3 behind OAuth2 with Python 3.", "files"), context(**career)) == []


def test_metrics_off_refuses_every_number_but_the_years() -> None:
    no_metrics = context(style={"metrics": False})

    assert codes(claim("I raised availability to 93%.", "acme-allocation"), no_metrics) == [
        ("NUMBERS_NOT_WANTED", "93")
    ]
    assert codes(claim("I have 5 years of experience.", "acme-allocation"), no_metrics) == []


def test_an_employer_must_belong_to_a_cited_fact() -> None:
    assert codes(claim("At Nimbus Commerce I built an allocation service.", "acme-allocation")) == [
        ("UNSUPPORTED_ORG", "Nimbus Commerce")
    ]
    assert codes(claim("At nimbus commerce I maintained listings.", "nimbus-apis")) == []
    assert codes(claim("I studied at Cairo University.", "bsc")) == []


@pytest.mark.parametrize(
    ("text", "word"),
    [
        ("As a senior engineer I built the allocation service.", "senior"),
        ("I led the allocation work.", "led"),
        ("I was the tech lead for allocation.", "lead"),
        ("As lead engineer I built allocation.", "lead"),
        ("I managed the allocation service team.", "managed"),
        ("I was engineering manager for allocation.", "manager"),
        ("I architected the allocation service.", "architect"),
        ("I am an expert in allocation.", "expert"),
        ("I was head of allocation.", "head of"),
        ("As co-founder I built allocation.", "founder"),
        ("As principal engineer I built allocation.", "principal"),
    ],
)
def test_a_word_of_rank_must_be_in_the_cited_facts(text: str, word: str) -> None:
    assert codes(claim(text, "acme-allocation")) == [("UNSUPPORTED_TITLE", word)]


def test_a_word_of_rank_that_the_fact_itself_uses_passes() -> None:
    career: dict[str, Any] = {
        "facts": [
            {
                "id": "team",
                "kind": "experience",
                "org": "Orbit",
                "role": "Tech Lead",
                "period": {"from": "2024-01"},
                "text": "Led a team that rebuilt billing.",
            }
        ]
    }

    assert codes(claim("As tech lead I led the billing rebuild.", "team"), context(**career)) == []


def test_words_that_only_look_like_rank_are_fine() -> None:
    assert (
        codes(claim("My work lead to fewer stock-outs; I am ahead of plan and manage my time.", "acme-allocation"))
        == []
    )


def test_the_jobs_own_title_and_company_are_not_claims() -> None:
    ctx = ClaimContext(
        example_career(), TODAY, "en", example_job(title="Senior Backend Engineer", company="Kafka Systems"), POSTING
    )

    assert codes(plain("I am writing about the Senior Backend Engineer role at Kafka Systems."), ctx) == []
    assert only(plain("I am a senior engineer."), ctx) == ["PLAIN_BLOCK_CLAIMS"]


def test_a_plain_block_says_nothing_about_the_person() -> None:
    assert codes(plain("Your work on moving 2 million parcels across KSA with Temporal caught my attention.")) == []
    assert codes(plain("I would love to talk.")) == []
    assert only(plain("I know Kafka well.")) == ["PLAIN_BLOCK_CLAIMS"]
    assert only(plain("I worked at Acme Retail.")) == ["PLAIN_BLOCK_CLAIMS"]
    assert only(plain("I led teams before.")) == ["PLAIN_BLOCK_CLAIMS"]
    assert only(plain("You move 5 million parcels.")) == ["PLAIN_BLOCK_CLAIMS"]
    assert only(plain("You use DynamoDB.")) == ["PLAIN_BLOCK_CLAIMS"]
    assert only(plain("I like your use of gRPC.")) == ["PLAIN_BLOCK_CLAIMS"]
    # A product name is fine when the posting itself uses it, and only then.
    assert codes(plain("ParcelOS is the kind of platform I want to work on.")) == []
    assert codes(plain("NovaDB is the kind of platform I want to work on.")) == [
        ("PLAIN_BLOCK_CLAIMS", "names something that is not in the posting: NovaDB")
    ]


def test_placeholders_and_format() -> None:
    assert only(claim("Dear [Hiring Team], I built allocation.", "acme-allocation")) == ["PLACEHOLDER"]
    assert only(plain("Hello {company} team.")) == ["PLACEHOLDER"]
    assert only(plain("Sincerely, Your Name")) == ["PLACEHOLDER"]
    assert "FORMAT" in only(plain("See https://example.com/me for more."))
    assert "FORMAT" in only(plain("Write to me at someone@example.com."))
    assert only(plain("Line one\nline two")) == ["FORMAT"]
    assert only(plain("<b>Hello</b> there")) == ["FORMAT"]
    assert only(plain("# A heading")) == ["FORMAT"]
    assert only(plain("   ")) == ["FORMAT"]


def test_length() -> None:
    assert only(claim("I built " + "very " * 60 + "good things.", "acme-allocation", section=Section.SUMMARY)) == [
        "TOO_LONG"
    ]
    assert only(claim("I built " + "very " * 60 + "good things.", "acme-allocation")) == []
    assert only(plain("word " * 150)) == ["TOO_LONG"]


def test_a_bullet_belongs_to_one_fact_of_the_right_kind() -> None:
    def bullet(fact: str | None, *cited: str, section: Section = Section.EXPERIENCE) -> list[str]:
        return only(claim("Built the allocation service.", *cited, section=section, fact=fact))

    assert bullet("acme-allocation", "acme-allocation") == []
    assert bullet("acme-allocation", "acme-allocation", "tooling") == []
    assert bullet(None, "acme-allocation") == ["WRONG_SECTION_FACT"]
    assert bullet("acme-allocation", "tooling") == ["WRONG_SECTION_FACT"]
    assert bullet("ledger-project", "ledger-project") == ["WRONG_SECTION_FACT"]
    assert bullet("ledger-project", "ledger-project", section=Section.PROJECT) == []
    assert bullet("bsc", "bsc", section=Section.PROJECT) == ["WRONG_SECTION_FACT"]


def test_a_bullet_is_always_a_claim_even_when_marked_plain() -> None:
    sneaky = Block(
        Section.EXPERIENCE, BlockKind.PLAIN, "Ran everything on Kubernetes.", ("acme-allocation",), "acme-allocation"
    )

    assert only(sneaky) == ["UNSUPPORTED_SKILL"]


def test_language() -> None:
    arabic = claim("بنيت خدمة توزيع المخزون باستخدام NestJS و Kafka و PostgreSQL.", "acme-allocation")
    english = claim("I built the allocation service with NestJS.", "acme-allocation")

    assert only(arabic, context("ar")) == []
    assert only(english, context("ar")) == ["WRONG_LANGUAGE"]
    assert only(arabic, context("en")) == ["WRONG_LANGUAGE"]
    assert only(english, context("en")) == []


def test_arabic_words_of_rank() -> None:
    assert only(claim("كنت مدير فريق التوزيع في Acme Retail.", "acme-allocation"), context("ar")) == [
        "UNSUPPORTED_TITLE"
    ]
    assert only(claim("قدت فريق التوزيع.", "acme-allocation"), context("ar")) == ["UNSUPPORTED_TITLE"]
    assert only(claim("بنيت خدمة التوزيع بكفاءة.", "acme-allocation"), context("ar")) == []


def test_a_block_made_of_its_facts_own_words_always_passes() -> None:
    ctx = context()
    for fact in ctx.career.facts:
        section = {"experience": Section.EXPERIENCE, "project": Section.PROJECT}.get(fact.kind.value, Section.BODY)
        own = fact.id if section is not Section.BODY else None

        assert codes(Block(section, BlockKind.CLAIM, fact.text, (fact.id,), own), ctx) == [], fact.id


def test_any_mix_of_a_facts_own_words_passes() -> None:
    ctx = context()
    rng = random.Random(3)
    for fact in ctx.career.facts:
        words = re.findall(r"\S+", fact.text)
        for _ in range(40):
            sample = " ".join(rng.sample(words, rng.randint(1, len(words))))
            found = [v for v in check_block(claim(sample, fact.id), 0, ctx) if v.code.startswith("UNSUPPORTED")]

            assert found == [], (fact.id, sample)


def blocks_of(*items: Block) -> tuple[Block, ...]:
    return items


def test_document_limits() -> None:
    ctx = context()
    summary = [claim("I build backend services.", "acme-allocation", section=Section.SUMMARY)] * 4
    bullets = [
        claim("Built the allocation service.", "acme-allocation", section=Section.EXPERIENCE, fact="acme-allocation")
    ] * 5

    violations = check_document(DocumentKind.CV, [*summary, *bullets], ctx)

    assert [(v.code, v.block) for v in violations] == [("TOO_LONG", 3), ("TOO_LONG", 8)]


def test_a_document_has_only_its_own_sections() -> None:
    ctx = context()

    in_cv = check_document(DocumentKind.CV, [plain("Hello there.")], ctx)
    in_letter = check_document(
        DocumentKind.COVER, [claim("I build services.", "acme-allocation", section=Section.SUMMARY)], ctx
    )

    assert [v.code for v in in_cv] == ["WRONG_SECTION"]
    assert [v.code for v in in_letter] == ["WRONG_SECTION"]


def test_a_letter_has_limits_on_paragraphs_and_on_total_length() -> None:
    ctx = context()
    paragraph = plain("I would love to talk about this role and what your team is building this year. " * 5)

    too_many = check_document(DocumentKind.OUTREACH, [plain("Hello.")] * 5, ctx)
    too_long = check_document(DocumentKind.OUTREACH, [paragraph, paragraph], ctx)

    assert [(v.code, v.block) for v in too_many] == [("TOO_LONG", 4)]
    assert [(v.code, v.block) for v in too_long] == [("TOO_LONG", 1)]


def test_check_document_reports_each_block_by_its_position() -> None:
    ctx = context()
    draft = [
        plain("Hello."),
        claim("I ran Kubernetes.", "acme-allocation"),
        claim("I built allocation.", "acme-allocation"),
    ]

    assert [(v.code, v.block) for v in check_document(DocumentKind.COVER, draft, ctx)] == [("UNSUPPORTED_SKILL", 1)]


def test_blocks_are_read_from_a_models_answer() -> None:
    raw = {
        "blocks": [
            {"section": "Body", "kind": "plain", "text": "  Hello.  "},
            {
                "section": "experience",
                "kind": "claim",
                "text": "- Built allocation.",
                "facts": ["acme-allocation", "acme-allocation", 7],
                "fact": "acme-allocation",
            },
            {"section": "summary", "text": "I build services.", "facts": "acme-allocation"},
            {"section": "body", "kind": "something", "text": "x"},
        ]
    }

    blocks = parse_blocks(raw).unwrap()

    assert blocks[0] == Block(Section.BODY, BlockKind.PLAIN, "Hello.")
    assert blocks[1] == Block(
        Section.EXPERIENCE, BlockKind.CLAIM, "Built allocation.", ("acme-allocation",), "acme-allocation"
    )
    assert (blocks[2].kind, blocks[2].facts) == (BlockKind.CLAIM, ())
    # Anything that is not clearly "plain" is checked as a claim.
    assert blocks[3].kind is BlockKind.CLAIM
    assert parse_blocks(raw["blocks"]).unwrap() == blocks


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        {"blocks": []},
        {"blocks": "text"},
        {"blocks": ["text"]},
        {"blocks": [{"section": "body"}]},
        {"blocks": [{"section": "footer", "text": "x"}]},
    ],
)
def test_a_draft_that_is_not_a_list_of_blocks_is_refused(raw: Any) -> None:
    result = parse_blocks(raw)

    assert result.value is None
    assert result.errors[0].code == "BLOCKS-SHAPE"
