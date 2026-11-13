from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from masar.domain.career import FactKind, checksum, parse_career
from masar.domain.findings import Severity
from tests.support.career import TODAY, example_career, example_data


def codes(data: Any) -> list[tuple[str, str]]:
    return [(f.code, f.path) for f in parse_career(data).errors]


def test_the_example_file_is_valid_and_has_no_errors() -> None:
    result = parse_career(example_data())

    assert result.ok
    career = result.unwrap()
    assert career.person.name == "Sara Al-Najjar"
    assert len(career.facts) == 8
    assert career.fact("acme-allocation") is not None
    assert career.fact("nope") is None


def test_a_file_that_is_not_a_mapping_is_refused() -> None:
    assert codes(["not", "a", "mapping"]) == [("CAREER-FIELD", "")]
    assert codes(None) == [("CAREER-FIELD", "")]


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda d: d.update(extra=1), ("CAREER-FIELD", "extra")),
        (lambda d: d["person"].update(nickname="S"), ("CAREER-FIELD", "person.nickname")),
        (lambda d: d["person"].pop("name"), ("CAREER-FIELD", "person.name")),
        (lambda d: d["person"]["location"].update(country="Egypt"), ("CAREER-CODE", "person.location.country")),
        (lambda d: d["person"].update(languages=[{"code": "arabic"}]), ("CAREER-CODE", "person.languages[0].code")),
        (lambda d: d["person"].update(work_authorization=["eg"]), ("CAREER-CODE", "person.work_authorization[0]")),
        (lambda d: d["limits"].update(countries=["SA", "UAE"]), ("CAREER-CODE", "limits.countries[1]")),
        (lambda d: d["limits"].update(remote="yes"), ("CAREER-FIELD", "limits.remote")),
        (lambda d: d["limits"].update(employment=["freelance"]), ("CAREER-FIELD", "limits.employment[0]")),
        (lambda d: d["limits"].update(years_gap_allowed=-1), ("CAREER-FIELD", "limits.years_gap_allowed")),
        (lambda d: d["limits"].update(salary=1), ("CAREER-FIELD", "limits.salary")),
        (lambda d: d["style"].update(metrics=1), ("CAREER-FIELD", "style.metrics")),
        (lambda d: d.update(facts=[]), ("CAREER-EMPTY", "facts")),
        (lambda d: d.pop("facts"), ("CAREER-EMPTY", "facts")),
        (lambda d: d["facts"][0].update(id="Acme Allocation"), ("CAREER-ID", "facts[0].id")),
        (lambda d: d["facts"][0].update(id="a"), ("CAREER-ID", "facts[0].id")),
        (lambda d: d["facts"][1].update(id="acme-allocation"), ("CAREER-ID", "facts[1].id")),
        (lambda d: d["facts"][0].update(kind="job"), ("CAREER-FIELD", "facts.acme-allocation.kind")),
        (lambda d: d["facts"][0].update(text="Short"), ("CAREER-TEXT", "facts.acme-allocation.text")),
        (lambda d: d["facts"][0].update(text="x" * 601), ("CAREER-TEXT", "facts.acme-allocation.text")),
        (lambda d: d["facts"][0].pop("org"), ("CAREER-EXPERIENCE", "facts.acme-allocation")),
        (lambda d: d["facts"][0].pop("period"), ("CAREER-EXPERIENCE", "facts.acme-allocation")),
        (
            lambda d: d["facts"][0].update(period={"from": "2024-13"}),
            ("CAREER-PERIOD", "facts.acme-allocation.period.from"),
        ),
        (
            lambda d: d["facts"][0].update(period={"from": "March 2023"}),
            ("CAREER-PERIOD", "facts.acme-allocation.period.from"),
        ),
        (
            lambda d: d["facts"][3].update(period={"from": "2023-02", "to": "2021-06"}),
            ("CAREER-PERIOD", "facts.nimbus-apis.period"),
        ),
        (lambda d: d["facts"][0].update(team="x"), ("CAREER-FIELD", "facts.acme-allocation.team")),
        (lambda d: d["facts"][0].update(skills="Kafka"), ("CAREER-FIELD", "facts.acme-allocation.skills")),
        (lambda d: d["facts"].append("just text"), ("CAREER-FIELD", "facts[8]")),
    ],
)
def test_each_rule_names_the_place_of_the_fault(change: Any, expected: tuple[str, str]) -> None:
    data = example_data()
    change(data)

    result = parse_career(data)

    assert expected in codes(data)
    assert result.value is None


def test_every_fault_is_reported_in_one_run() -> None:
    data = example_data()
    data["facts"][0]["id"] = "Bad Id"
    data["facts"][1]["text"] = "tiny"
    data["limits"]["countries"] = ["xx"]

    found = {code for code, _ in codes(data)}

    assert found == {"CAREER-ID", "CAREER-TEXT", "CAREER-CODE"}


def test_weak_spots_are_warnings_and_do_not_block() -> None:
    data = example_data()
    data["facts"][0]["skills"] = []
    data["facts"][2]["text"] = "Built a multi-agent customer support assistant for order questions."

    result = parse_career(data)

    assert result.ok
    warnings = {(f.code, f.path) for f in result.warnings}
    assert ("CAREER-NO-SKILLS", "facts.acme-allocation") in warnings
    assert ("CAREER-NO-NUMBERS", "facts.acme-support-agent") in warnings
    assert all(f.severity is Severity.WARNING for f in result.findings)


def test_a_thin_file_and_metrics_off() -> None:
    data = example_data()
    data["facts"] = data["facts"][:2]
    data["style"]["metrics"] = False
    data["facts"][0]["text"] = "Built an event-driven inventory allocation service."

    result = parse_career(data)

    assert ("CAREER-THIN", "facts") in {(f.code, f.path) for f in result.warnings}
    assert "CAREER-NO-NUMBERS" not in {f.code for f in result.warnings}


def test_sections_may_be_left_out_and_get_their_defaults() -> None:
    data = example_data()
    del data["limits"], data["style"]
    data["person"] = {"name": "A Person"}

    career = parse_career(data).unwrap()

    assert career.limits.remote
    assert career.limits.relocation
    assert career.limits.years_gap_allowed == 2
    assert career.limits.countries == frozenset()
    assert career.style.metrics
    assert career.person.location is None
    assert career.person.languages == ()


def test_a_language_may_be_written_as_a_bare_code() -> None:
    data = example_data()
    data["person"]["languages"] = ["ar", {"code": "en"}]

    assert [lang.code for lang in parse_career(data).unwrap().person.languages] == ["ar", "en"]


def test_years_of_experience_count_overlapping_months_once() -> None:
    career = example_career()

    # 2021-06 .. 2023-02 (21 months) and 2023-03 .. 2026-11 (45 months), three facts on the same months.
    assert career.months_of_experience(TODAY) == 66
    assert career.years_of_experience(TODAY) == pytest.approx(5.5)


def test_years_of_experience_stop_at_today_and_skip_gaps() -> None:
    career = example_career()

    assert career.months_of_experience(date(2021, 5, 31)) == 0
    assert career.months_of_experience(date(2021, 6, 1)) == 1
    assert career.months_of_experience(date(2023, 3, 15)) == 22

    data = example_data()
    data["facts"] = [f for f in data["facts"] if f.get("org") == "Nimbus Commerce"] + [
        {
            "id": "later",
            "kind": "experience",
            "org": "Later",
            "role": "Engineer",
            "period": {"from": "2024-01", "to": "2024-06"},
            "text": "Worked on later things.",
        }
    ]
    with_gap = parse_career(data).unwrap()
    assert with_gap.months_of_experience(TODAY) == 21 + 6


def test_projects_and_education_do_not_count_as_experience() -> None:
    data = example_data()
    data["facts"] = [f for f in data["facts"] if f["kind"] != "experience"]

    assert parse_career(data).unwrap().months_of_experience(TODAY) == 0


def test_skills_are_derived_by_canonical_name() -> None:
    career = example_career()

    assert {"kafka", "postgresql", "node.js", "nestjs", "langgraph", "aws"} <= career.skills
    assert career.skill_spellings.count("Node.js") == 1
    assert [f.id for f in career.facts_with_skill("postgres")] == ["acme-allocation", "ledger-project"]
    assert career.facts_with_skill("Rust") == ()
    assert career.organizations == ("Acme Retail", "Nimbus Commerce", "Cairo University")


def test_the_person_never_prints_contact_details() -> None:
    career = example_career()

    assert "sara@example.com" not in repr(career)
    assert "+20" not in repr(career.person)


def test_kinds_and_periods_read_as_written() -> None:
    career = example_career()
    fact = career.fact("nimbus-apis")

    assert fact is not None
    assert fact.kind is FactKind.EXPERIENCE
    assert str(fact.period) == "2021-06 to 2023-02"
    assert fact.period is not None
    assert fact.period.years == {2021, 2023}
    current = career.fact("acme-allocation")
    assert current is not None
    assert str(current.period) == "2023-03 to present"
    assert current.period is not None
    assert current.period.years == {2023}


def test_the_checksum_follows_the_bytes() -> None:
    assert checksum(b"a") == checksum(b"a")
    assert checksum(b"a") != checksum(b"b")
    assert len(checksum(b"")) == 64
