from __future__ import annotations

import random
from typing import Any

import pytest

from masar.domain.career import Career
from masar.domain.job import Employment, JobLocation, RequirementKind, Seniority, Sponsorship, Workplace
from masar.domain.matching import (
    Assessment,
    Flag,
    FlagSeverity,
    Recommendation,
    RequirementAssessment,
    ScoreSettings,
    Verdict,
    check_evidence,
    is_lower_or_equal,
    recommend,
    score,
    screen,
    title_matches,
)
from tests.support.career import TODAY, career_with, example_career
from tests.support.jobs import example_job, requirement


def flags(job: Any = None, career: Career | None = None) -> dict[str, FlagSeverity]:
    return {f.code: f.severity for f in screen(job or example_job(), career or example_career(), TODAY)}


B, W = FlagSeverity.BLOCKER, FlagSeverity.WARNING


def test_a_job_that_fits_has_no_flags() -> None:
    assert flags() == {}


def test_excluded_company() -> None:
    assert flags(career=career_with(limits={"exclude_companies": ["tamween"]})) == {"COMPANY_EXCLUDED": B}
    assert flags(career=career_with(limits={"exclude_companies": ["Tam"]})) == {}


def test_employment_type() -> None:
    assert flags(example_job(employment=Employment.CONTRACT)) == {"EMPLOYMENT_NOT_WANTED": B}
    assert flags(example_job(employment=Employment.UNKNOWN)) == {}
    assert flags(example_job(employment=Employment.CONTRACT), career_with(limits={"employment": []})) == {}


def test_remote_jobs() -> None:
    remote = example_job(workplace=Workplace.REMOTE, locations=())

    assert flags(remote) == {}
    assert flags(remote, career_with(limits={"remote": False})) == {"REMOTE_NOT_WANTED": B}
    # A remote job tied to a country where the person may not work: look, do not skip.
    assert flags(
        example_job(
            workplace=Workplace.REMOTE, locations=(JobLocation(None, "DE"),), sponsorship=Sponsorship.NOT_OFFERED
        )
    ) == {"REMOTE_REGION": W}
    assert flags(example_job(workplace=Workplace.REMOTE, locations=(JobLocation(None, "EG"),))) == {}


def test_country_not_wanted() -> None:
    germany = example_job(locations=(JobLocation("Berlin", "DE"),))

    assert flags(germany) == {"COUNTRY_NOT_WANTED": B}
    assert flags(example_job(locations=(JobLocation("Berlin", "DE"), JobLocation("Dubai", "AE")))) == {}
    assert flags(germany, career_with(limits={"countries": []})) == {}
    # One place without a country: the posting did not say enough to block.
    assert "COUNTRY_NOT_WANTED" not in flags(
        example_job(locations=(JobLocation("Berlin", "DE"), JobLocation("Somewhere", None)))
    )


def test_no_relocation() -> None:
    stay = career_with(limits={"relocation": False})

    assert flags(career=stay) == {"NO_RELOCATION": B}
    assert flags(example_job(locations=(JobLocation("Cairo", "EG"),)), stay) == {}
    assert flags(example_job(workplace=Workplace.REMOTE), stay) == {"REMOTE_REGION": W}


def test_sponsorship() -> None:
    assert flags(example_job(sponsorship=Sponsorship.NOT_OFFERED)) == {"SPONSORSHIP_NOT_OFFERED": B}
    assert flags(example_job(sponsorship=Sponsorship.UNKNOWN)) == {"SPONSORSHIP_UNKNOWN": W}
    assert flags(example_job(sponsorship=Sponsorship.NOT_OFFERED, locations=(JobLocation("Cairo", "EG"),))) == {}
    # The person did not say where they may work: warn, never block.
    nowhere = career_with(person={"work_authorization": []})
    assert flags(example_job(sponsorship=Sponsorship.NOT_OFFERED), nowhere) == {"SPONSORSHIP_UNKNOWN": W}


def test_years_of_experience() -> None:
    # The example person has 5.5 years and allows a gap of 2.
    assert flags(example_job(min_years=5)) == {}
    assert flags(example_job(min_years=6)) == {"YEARS_BELOW": W}
    assert flags(example_job(min_years=7)) == {"YEARS_BELOW": W}
    assert flags(example_job(min_years=8)) == {"YEARS_FAR_BELOW": B}
    assert flags(example_job(min_years=6), career_with(limits={"years_gap_allowed": 0})) == {"YEARS_FAR_BELOW": B}


def test_seniority_is_a_guess_and_only_warns() -> None:
    assert flags(example_job(min_years=None, seniority=Seniority.SENIOR)) == {}
    assert flags(example_job(min_years=None, seniority=Seniority.PRINCIPAL)) == {"SENIORITY_ABOVE": W}
    assert flags(example_job(min_years=None, seniority=Seniority.UNKNOWN)) == {}
    # A number in the posting wins over the title.
    assert flags(example_job(min_years=3, seniority=Seniority.PRINCIPAL)) == {}


def test_required_language() -> None:
    assert flags(example_job(languages=("en", "fr"))) == {"LANGUAGE_MISSING": B}
    assert flags(example_job(languages=("ar", "en"))) == {}
    assert flags(example_job(languages=("fr",)), career_with(person={"languages": []})) == {}


def test_missing_information_never_blocks() -> None:
    vague = example_job(
        workplace=Workplace.UNKNOWN,
        locations=(),
        min_years=None,
        seniority=Seniority.UNKNOWN,
        employment=Employment.UNKNOWN,
        sponsorship=Sponsorship.UNKNOWN,
        languages=(),
    )

    assert flags(vague) == {"WORKPLACE_UNKNOWN": W, "LOCATION_UNKNOWN": W}


def test_an_unknown_workplace_turns_location_blockers_into_warnings() -> None:
    maybe_remote = example_job(
        workplace=Workplace.UNKNOWN, locations=(JobLocation("Berlin", "DE"),), sponsorship=Sponsorship.NOT_OFFERED
    )

    found = flags(maybe_remote, career_with(limits={"relocation": False}))

    assert found == {"WORKPLACE_UNKNOWN": W, "COUNTRY_NOT_WANTED": W, "NO_RELOCATION": W, "SPONSORSHIP_NOT_OFFERED": W}


def test_flag_messages_say_what_and_why() -> None:
    message = next(f.message for f in screen(example_job(min_years=9), example_career(), TODAY))

    assert message == "the posting asks for 9 years; you have 5.5 years"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Senior Backend Engineer", True),
        ("Back-end Engineer (Node.js)", True),
        ("Software Engineer, Payments", True),
        ("AI Engineer", True),
        ("Backend Engineering Intern", False),
        ("Internal Tools Backend Engineer", True),
        ("Sales Engineer", False),
        ("Engineering Manager, Backend", False),
        ("Product Designer", False),
        ("Backends", False),
    ],
)
def test_title_filter(title: str, expected: bool) -> None:
    assert title_matches(title, example_career().limits) is expected


def test_title_filter_with_no_keywords_keeps_everything_not_excluded() -> None:
    limits = career_with(limits={"title_keywords": [], "title_exclude": ["intern"]}).limits

    assert title_matches("Product Designer", limits)
    assert not title_matches("Design Intern", limits)


def raw(*entries: tuple[str, str, list[str]]) -> dict[str, Any]:  # (requirement, verdict, evidence)
    return {"assessments": [{"requirement": r, "verdict": v, "evidence": e, "note": "because"} for r, v, e in entries]}


GOOD = raw(
    ("r1", "met", ["acme-allocation", "nimbus-apis"]),
    ("r2", "met", ["acme-support-agent"]),
    ("r3", "met", ["acme-allocation"]),
    ("r4", "missing", []),
)


def checked(assessment: Any, job: Any = None) -> tuple[Assessment, list[str]]:
    result = check_evidence(job or example_job(), example_career(), assessment)
    return result.unwrap(), [f.code for f in result.findings]


def test_a_supported_assessment_is_kept_and_skill_facts_are_added_as_evidence() -> None:
    assessment, codes = checked(GOOD)

    assert codes == []
    assert [i.verdict for i in assessment.items] == [Verdict.MET, Verdict.MET, Verdict.MET, Verdict.MISSING]
    assert all(i.by == "model" and i.lowered_from is None for i in assessment.items)
    r2 = assessment.of("r2")
    assert r2 is not None
    assert r2.evidence[0] == "acme-support-agent"
    assert set(r2.evidence) == {"acme-support-agent", "acme-receiving", "nimbus-apis", "nimbus-payments"}
    assert assessment.of("r4") == RequirementAssessment("r4", Verdict.MISSING, note="because")
    assert assessment.of("r9") is None


def test_e1_unknown_facts_are_dropped_from_the_evidence() -> None:
    first = {"requirement": "r1", "verdict": "met", "evidence": ["acme-allocation", "made-up", 7], "note": ""}

    assessment, codes = checked({"assessments": [first, *GOOD["assessments"][1:]]})

    assert codes == ["EVIDENCE-UNKNOWN-FACT", "EVIDENCE-UNKNOWN-FACT"]
    r1 = assessment.of("r1")
    assert r1 is not None
    assert (r1.verdict, r1.evidence) == (Verdict.MET, ("acme-allocation",))


def test_e2_a_verdict_with_no_evidence_left_is_missing() -> None:
    assessment, codes = checked(
        raw(("r1", "met", ["made-up"]), ("r2", "partial", []), ("r3", "missing", []), ("r4", "missing", []))
    )

    r1 = assessment.of("r1")
    assert r1 is not None
    assert (r1.verdict, r1.by, r1.lowered_from, r1.reason, r1.evidence) == (
        Verdict.MISSING,
        "code",
        Verdict.MET,
        "no evidence",
        (),
    )
    # r2 names skills the person has, so code finds the evidence itself and the partial stays.
    r2 = assessment.of("r2")
    assert r2 is not None
    assert r2.verdict is Verdict.PARTIAL
    assert r2.evidence
    assert "EVIDENCE-NONE" in codes


def test_e3_met_for_a_named_skill_needs_a_fact_with_that_skill() -> None:
    # The person has no Kubernetes anywhere. The model cites a real but unrelated fact.
    assessment, codes = checked(
        raw(
            *[
                (r, v, e)
                for r, v, e in [
                    ("r1", "met", ["nimbus-apis"]),
                    ("r2", "met", ["nimbus-apis"]),
                    ("r3", "met", ["acme-allocation"]),
                    ("r4", "met", ["tooling"]),
                ]
            ]
        )
    )

    r4 = assessment.of("r4")
    assert r4 is not None
    # Nothing of a "met" that code can see is false stands, not even half of it.
    assert (r4.verdict, r4.by, r4.lowered_from, r4.reason) == (
        Verdict.MISSING,
        "code",
        Verdict.MET,
        "no fact shows: Kubernetes",
    )
    assert r4.evidence == ()
    assert codes == ["EVIDENCE-SKILL"]


def test_e3_partial_for_a_skill_the_person_lacks_is_the_models_call() -> None:
    # "Something close" is a judgement. It stays, with the fact the model named, and it is never more than partial.
    assessment, codes = checked(raw(("r4", "partial", ["tooling"])))

    r4 = assessment.of("r4")
    assert r4 is not None
    assert (r4.verdict, r4.by, r4.lowered_from, r4.evidence) == (Verdict.PARTIAL, "model", None, ("tooling",))
    assert "EVIDENCE-SKILL" not in codes


def test_e3_all_skills_means_every_one() -> None:
    job = example_job(
        requirements=(
            requirement(1, "Postgres and Kubernetes together", "PostgreSQL", "Kubernetes", all_skills=True),
            requirement(2, "Postgres or Kubernetes", "PostgreSQL", "Kubernetes"),
        )
    )

    assessment, _ = checked(raw(("r1", "met", ["acme-allocation"]), ("r2", "met", ["acme-allocation"])), job)

    assert [i.verdict for i in assessment.items] == [Verdict.PARTIAL, Verdict.MET]


def test_e3_a_met_with_no_evidence_and_no_skill_ends_as_missing() -> None:
    assessment, codes = checked(raw(("r4", "met", [])))

    r4 = assessment.of("r4")
    assert r4 is not None
    assert (r4.verdict, r4.lowered_from) == (Verdict.MISSING, Verdict.MET)
    assert "EVIDENCE-SKILL" in codes


def test_e4_a_requirement_the_model_skipped_is_missing_by_code() -> None:
    assessment, codes = checked(raw(("r1", "met", ["nimbus-apis"])))

    assert codes.count("EVIDENCE-NOT-ASSESSED") == 3
    r3 = assessment.of("r3")
    assert r3 is not None
    assert (r3.verdict, r3.by, r3.reason) == (Verdict.MISSING, "code", "not assessed")


def test_e5_unknown_and_repeated_requirements_are_ignored() -> None:
    assessment, codes = checked(
        {
            "assessments": [
                *GOOD["assessments"],
                {"requirement": "r99", "verdict": "met", "evidence": ["bsc"]},
                {"requirement": "r1", "verdict": "missing"},
                "text",
                {"verdict": "met"},
            ]
        }
    )

    assert codes == ["EVIDENCE-UNKNOWN-REQUIREMENT"] * 4
    r1 = assessment.of("r1")
    assert r1 is not None
    assert r1.verdict is Verdict.MET


def test_e6_notes_are_cut_and_odd_values_are_safe() -> None:
    entries = [
        {"requirement": "r1", "verdict": "MET ", "evidence": "nimbus-apis", "note": "x" * 400},
        {"requirement": "r2", "verdict": "definitely", "evidence": ["nimbus-apis"], "note": 5},
    ]

    assessment, _ = checked({"assessments": entries})

    r1, r2 = assessment.of("r1"), assessment.of("r2")
    assert r1 is not None
    assert r2 is not None
    assert len(r1.note) == 300
    assert r1.verdict is Verdict.MISSING  # evidence was not a list, so nothing is behind the verdict
    assert (r2.verdict, r2.note) == (Verdict.MISSING, "")


def test_the_model_overlooking_a_skill_is_reported_but_not_raised() -> None:
    assessment, codes = checked(
        raw(("r1", "met", ["nimbus-apis"]), ("r2", "missing", []), ("r3", "missing", []), ("r4", "missing", []))
    )

    r2 = assessment.of("r2")
    assert r2 is not None
    assert r2.verdict is Verdict.MISSING
    assert codes == ["EVIDENCE-OVERLOOKED", "EVIDENCE-OVERLOOKED"]


def test_an_assessment_may_be_a_bare_list_or_nonsense() -> None:
    assert checked(GOOD["assessments"])[0].items[0].verdict is Verdict.MET
    assert [i.verdict for i in checked("nonsense")[0].items] == [Verdict.MISSING] * 4
    assert [i.verdict for i in checked(None)[0].items] == [Verdict.MISSING] * 4


def test_code_never_raises_a_verdict() -> None:
    career = example_career()
    job = example_job()
    fact_ids = [*career.fact_ids, "made-up"]
    rng = random.Random(7)
    for _ in range(300):
        proposed = {r.id: rng.choice(["met", "partial", "missing", "nonsense"]) for r in job.requirements}
        assessment = check_evidence(
            job, career, raw(*[(r, v, rng.sample(fact_ids, rng.randint(0, 3))) for r, v in proposed.items()])
        ).unwrap()

        for item in assessment.items:
            said = (
                Verdict(proposed[item.requirement_id])
                if proposed[item.requirement_id] != "nonsense"
                else Verdict.MISSING
            )
            assert is_lower_or_equal(item.verdict, said)
            assert item.verdict is Verdict.MISSING or item.evidence
            assert set(item.evidence) <= career.fact_ids


def assessment_of(*verdicts: Verdict) -> Assessment:
    return Assessment(tuple(RequirementAssessment(f"r{i + 1}", v) for i, v in enumerate(verdicts)))


M, P, X = Verdict.MET, Verdict.PARTIAL, Verdict.MISSING


@pytest.mark.parametrize(
    ("verdicts", "expected"),
    [
        ((M, M, M, M), 100),
        ((X, X, X, X), 0),
        ((M, M, M, X), 90),  # three must-haves of weight 3, one nice-to-have of weight 1
        ((M, M, X, M), 70),
        ((P, P, P, P), 50),
        ((M, P, X, P), 50),
        ((M, X, X, X), 30),
        ((X, X, X, M), 10),
        ((M, M, P, X), 75),
    ],
)
def test_score_by_hand(verdicts: tuple[Verdict, ...], expected: int) -> None:
    assert score(example_job(), assessment_of(*verdicts)) == expected


def test_the_score_is_rounded_half_up() -> None:
    three = example_job(requirements=example_job().requirements[:3])
    eight = example_job(
        requirements=tuple(
            requirement(i, f"Nice thing number {i} to have", kind=RequirementKind.NICE) for i in range(1, 9)
        )
    )

    assert score(three, assessment_of(M, M, X)) == 67  # 66.67
    assert score(eight, assessment_of(M, X, X, X, X, X, X, X)) == 13  # 12.5


def test_score_edges() -> None:
    assert score(example_job(requirements=()), Assessment(())) is None
    # A requirement with no assessment counts as missing.
    assert score(example_job(), Assessment((RequirementAssessment("r1", M),))) == 30
    assert score(example_job(), assessment_of(M, X, X, M), ScoreSettings(must_weight=1, nice_weight=1)) == 50
    only_nice = example_job(requirements=(requirement(1, "Nice thing to have here", kind=RequirementKind.NICE),))
    assert score(only_nice, assessment_of(P)) == 50


def test_a_better_verdict_never_lowers_the_score() -> None:
    job = example_job()
    rng = random.Random(11)
    better = {X: P, P: M, M: M}
    for _ in range(200):
        verdicts = [rng.choice([M, P, X]) for _ in job.requirements]
        base = score(job, assessment_of(*verdicts))
        assert base is not None
        assert 0 <= base <= 100
        for i, verdict in enumerate(verdicts):
            improved = [*verdicts[:i], better[verdict], *verdicts[i + 1 :]]
            after = score(job, assessment_of(*improved))
            assert after is not None
            assert after >= base


BLOCK = (Flag("X", FlagSeverity.BLOCKER, "x"),)
WARN = (Flag("Y", FlagSeverity.WARNING, "y"),)


@pytest.mark.parametrize(
    ("points", "found", "expected"),
    [
        (100, BLOCK, Recommendation.SKIP),
        (100, WARN, Recommendation.APPLY),
        (70, (), Recommendation.APPLY),
        (69, (), Recommendation.MAYBE),
        (50, (), Recommendation.MAYBE),
        (49, (), Recommendation.SKIP),
        (0, (), Recommendation.SKIP),
        (None, (), Recommendation.MAYBE),
        (None, BLOCK, Recommendation.SKIP),
    ],
)
def test_recommendation(points: int | None, found: tuple[Flag, ...], expected: Recommendation) -> None:
    assert recommend(points, found) is expected


def test_recommendation_limits_are_settings() -> None:
    assert recommend(60, (), ScoreSettings(apply_from=60)) is Recommendation.APPLY
    assert recommend(40, (), ScoreSettings(maybe_from=40)) is Recommendation.MAYBE
