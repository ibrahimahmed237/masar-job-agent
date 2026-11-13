from __future__ import annotations

from typing import Any

from masar.domain.job import (
    Employment,
    Posting,
    RequirementKind,
    Seniority,
    Source,
    Sponsorship,
    Workplace,
    ground_job,
)

TEXT = """Backend Engineer at Tamween

We are a logistics company in Riyadh. This is a hybrid role.

What you bring:
- 3+ years of experience building backend services
- Strong knowledge of Node.js or Python
- Experience with Postgres and Kafka in production
- Fluent English; Arabic is a plus

Nice to have:
- Experience with Kubernetes

We are unable to sponsor visas for this role.
"""

POSTING = Posting(Source.MANUAL, "Tamween", "Backend Engineer", TEXT)


def candidate(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "seniority": "mid",
        "employment": "full-time",
        "workplace": "hybrid",
        "locations": [{"city": "Riyadh", "country": "SA"}],
        "min_years": {"value": 3, "quote": "3+ years of experience"},
        "sponsorship": {"status": "not_offered", "quote": "We are unable to sponsor visas"},
        "languages": [{"code": "en", "quote": "Fluent English"}],
        "requirements": [
            {"text": "Backend experience", "kind": "must", "quote": "3+ years of experience building backend services"},
            {
                "text": "Node.js or Python",
                "kind": "must",
                "skills": ["Node.js", "Python"],
                "quote": "Strong knowledge of Node.js or Python",
            },
            {
                "text": "Postgres and Kafka",
                "kind": "must",
                "skills": ["PostgreSQL", "Kafka"],
                "all_skills": True,
                "quote": "Experience with Postgres and Kafka in production",
            },
            {"text": "Kubernetes", "kind": "nice", "skills": ["Kubernetes"], "quote": "Experience with Kubernetes"},
        ],
    }
    base.update(changes)
    return base


def test_a_supported_reading_is_kept_whole() -> None:
    result = ground_job(candidate(), POSTING)

    job = result.unwrap()
    assert result.findings == ()
    assert (job.title, job.company) == ("Backend Engineer", "Tamween")
    assert (job.seniority, job.employment, job.workplace) == (Seniority.MID, Employment.FULL_TIME, Workplace.HYBRID)
    assert job.countries == {"SA"}
    assert job.min_years == 3
    assert job.sponsorship is Sponsorship.NOT_OFFERED
    assert job.languages == ("en",)
    assert [r.id for r in job.requirements] == ["r1", "r2", "r3", "r4"]
    assert [r.kind for r in job.requirements] == [RequirementKind.MUST] * 3 + [RequirementKind.NICE]
    assert job.requirements[2].all_skills
    assert job.requirements[2].skill_names == {"postgresql", "kafka"}
    assert job.skills == ("Node.js", "Python", "PostgreSQL", "Kafka", "Kubernetes")
    assert job.requirement("r4") is not None
    assert job.requirement("r9") is None


def test_the_title_and_company_come_from_the_posting_not_from_the_reading() -> None:
    job = ground_job(candidate(title="CEO", company="Evil Corp"), POSTING).unwrap()

    assert (job.title, job.company) == ("Backend Engineer", "Tamween")


def test_a_requirement_whose_quote_is_not_in_the_posting_is_dropped() -> None:
    made_up = {"text": "Rust expert", "kind": "must", "skills": ["Rust"], "quote": "10 years of Rust experience"}
    reading = candidate()
    reading["requirements"].insert(1, made_up)

    result = ground_job(reading, POSTING)

    job = result.unwrap()
    assert [r.id for r in job.requirements] == ["r1", "r2", "r3", "r4"]
    assert "Rust" not in job.skills
    assert [(f.code, f.path) for f in result.warnings] == [("JOB-QUOTE", "requirements[1]")]


def test_a_quote_too_short_to_mean_anything_is_refused() -> None:
    reading = candidate(
        requirements=[{"text": "Something", "quote": "a"}, {"text": "x", "quote": "Experience with Kubernetes"}]
    )

    result = ground_job(reading, POSTING)

    assert len(result.unwrap().requirements) == 1
    assert result.warnings[0].code == "JOB-QUOTE"


def test_quotes_are_compared_after_normalization() -> None:
    reading = candidate(requirements=[{"text": "x", "quote": "strong   knowledge of NODE.JS or python"}])

    assert ground_job(reading, POSTING).unwrap().requirements[0].quote == "strong knowledge of NODE.JS or python"


def test_a_skill_must_be_in_its_requirements_quote_under_any_spelling() -> None:
    reading = candidate(
        requirements=[
            {
                "text": "Stores",
                "skills": ["PostgreSQL", "Kafka", "Redis", "Kafka"],
                "quote": "Experience with Postgres and Kafka in production",
            }
        ]
    )

    result = ground_job(reading, POSTING)

    assert result.unwrap().requirements[0].skills == ("PostgreSQL", "Kafka")
    assert [(f.code, f.message) for f in result.warnings] == [
        ("JOB-SKILL", "skill dropped: 'Redis' is not in the requirement's quote")
    ]


def test_the_same_quote_twice_is_one_requirement() -> None:
    twice = [
        {"text": "a", "quote": "Experience with Kubernetes"},
        {"text": "b", "quote": "experience with  kubernetes"},
    ]

    assert len(ground_job(candidate(requirements=twice), POSTING).unwrap().requirements) == 1


def test_all_skills_needs_more_than_one_skill_and_kind_defaults_to_must() -> None:
    reading = candidate(
        requirements=[
            {
                "text": "x",
                "skills": ["Kubernetes"],
                "all_skills": True,
                "quote": "Experience with Kubernetes",
                "kind": "whatever",
            }
        ]
    )

    requirement = ground_job(reading, POSTING).unwrap().requirements[0]

    assert not requirement.all_skills
    assert requirement.kind is RequirementKind.MUST


def test_no_requirement_left_means_no_job() -> None:
    for reading in (
        candidate(requirements=[]),
        candidate(requirements=None),
        candidate(requirements=[{"quote": "not in the posting at all"}, "text"]),
    ):
        result = ground_job(reading, POSTING)

        assert result.value is None
        assert result.errors[-1].code == "JOB-EMPTY"


def test_a_reading_that_is_not_an_object_is_refused() -> None:
    assert ground_job(["x"], POSTING).errors[0].code == "JOB-SHAPE"


def test_min_years_needs_a_quote_with_the_number() -> None:
    assert (
        ground_job(candidate(min_years={"value": 5, "quote": "3+ years of experience"}), POSTING).unwrap().min_years
        is None
    )
    assert (
        ground_job(candidate(min_years={"value": 3, "quote": "many years of experience"}), POSTING).unwrap().min_years
        is None
    )
    assert ground_job(candidate(min_years={"value": 3}), POSTING).unwrap().min_years is None
    assert (
        ground_job(candidate(min_years={"value": 3, "quote": "3 years on the moon"}), POSTING).unwrap().min_years
        is None
    )
    assert (
        ground_job(candidate(min_years={"value": "3", "quote": "3+ years of experience"}), POSTING).unwrap().min_years
        is None
    )
    assert ground_job(candidate(min_years=None), POSTING).unwrap().min_years is None
    result = ground_job(candidate(min_years={"value": 30, "quote": "3+ years of experience"}), POSTING)
    assert result.unwrap().min_years is None
    assert result.warnings[0].code == "JOB-YEARS"


def test_min_years_may_be_written_in_words() -> None:
    posting = Posting(
        Source.MANUAL, "X", "Y", TEXT.replace("3+ years of experience building", "three years of experience building")
    )
    reading = candidate(
        min_years={"value": 3, "quote": "three years of experience"},
        requirements=[{"text": "x", "quote": "Experience with Kubernetes"}],
    )

    assert ground_job(reading, posting).unwrap().min_years == 3


def test_a_sponsorship_statement_needs_its_quote() -> None:
    invented = ground_job(
        candidate(sponsorship={"status": "offered", "quote": "We sponsor visas for everyone"}), POSTING
    )
    missing = ground_job(candidate(sponsorship={"status": "offered"}), POSTING)

    assert invented.unwrap().sponsorship is Sponsorship.UNKNOWN
    assert invented.warnings[0].code == "JOB-SPONSORSHIP"
    assert missing.unwrap().sponsorship is Sponsorship.UNKNOWN
    assert ground_job(candidate(sponsorship="offered"), POSTING).unwrap().sponsorship is Sponsorship.UNKNOWN
    assert ground_job(candidate(sponsorship={"status": "unknown"}), POSTING).findings == ()


def test_a_required_language_needs_its_quote() -> None:
    reading = candidate(
        languages=[
            {"code": "en", "quote": "Fluent English"},
            {"code": "fr", "quote": "Fluent French"},
            {"code": "english", "quote": "Fluent English"},
            {"code": "EN", "quote": "Fluent English"},
        ]
    )

    result = ground_job(reading, POSTING)

    assert result.unwrap().languages == ("en",)
    assert [f.code for f in result.warnings] == ["JOB-LANGUAGE", "JOB-LANGUAGE"]


def test_unknown_words_become_unknown_and_locations_are_tidied() -> None:
    reading = candidate(
        seniority="wizard",
        employment="Full Time",
        workplace=None,
        locations=[
            {"city": "Riyadh", "country": "sa"},
            {"city": "Riyadh", "country": "SA"},
            {"country": "Saudi Arabia"},
            {},
            "x",
        ],
    )

    result = ground_job(reading, POSTING)

    job = result.unwrap()
    assert (job.seniority, job.employment, job.workplace) == (
        Seniority.UNKNOWN,
        Employment.FULL_TIME,
        Workplace.UNKNOWN,
    )
    assert [(p.city, p.country) for p in job.locations] == [("Riyadh", "SA")]
    assert [f.code for f in result.warnings] == ["JOB-LOCATION"]


def test_at_most_forty_requirements_are_kept() -> None:
    lines = [f"- Requirement number {i:02d} is about a thing" for i in range(45)]
    posting = Posting(Source.MANUAL, "X", "Y", "\n".join(lines))
    reading = {"requirements": [{"text": f"r{i}", "quote": line[2:]} for i, line in enumerate(lines)]}

    result = ground_job(reading, posting)

    assert len(result.unwrap().requirements) == 40
    assert result.warnings[-1].code == "JOB-TOO-MANY"


def test_a_long_requirement_text_is_cut() -> None:
    reading = candidate(requirements=[{"text": "x" * 500, "quote": "Experience with Kubernetes"}])

    assert len(ground_job(reading, POSTING).unwrap().requirements[0].text) == 300


def test_the_same_content_is_the_same_posting() -> None:
    again = Posting(
        Source.GREENHOUSE,
        "tamween",
        " Backend  Engineer ",
        TEXT.replace("\n", "\n\n"),
        url="https://x",
        external_id="1",
    )
    other = Posting(Source.MANUAL, "Tamween", "Backend Engineer", TEXT + " One more line.")

    assert POSTING.checksum == again.checksum
    assert POSTING.checksum != other.checksum


def test_what_the_model_writes_about_a_requirement_is_kept_without_hidden_characters() -> None:
    posting = Posting(Source.MANUAL, "Tamween", "Backend Engineer", "We ask for strong knowledge of Python.")
    reading = {
        "requirements": [
            {"text": "Python\x1b[31m, strongly", "quote": "strong knowledge of Python", "skills": ["Python"]}
        ]
    }
    job = ground_job(reading, posting).unwrap()
    assert job.requirements[0].text == "Python[31m, strongly"
