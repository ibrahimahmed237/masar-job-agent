from __future__ import annotations

import pytest

from masar.domain.skills import SkillLexicon, canonical, canonical_set, display, is_known, spellings
from masar.domain.text import arabic_share, contains, has_unseen, normalize, plain_name, western_digits, without_unseen


@pytest.mark.parametrize(
    ("written", "name"),
    [
        ("Postgres", "postgresql"),
        ("PostgreSQL", "postgresql"),
        ("psql", "postgresql"),
        ("K8s", "kubernetes"),
        ("NodeJS", "node.js"),
        ("node js", "node.js"),
        ("  Node.js ", "node.js"),
        ("Golang", "go"),
        ("ASP.NET Core", ".net"),
        ("dotnet", ".net"),
        ("C#", "c#"),
        ("csharp", "c#"),
        ("Temporal", "temporal"),
    ],
)
def test_spellings_map_to_one_canonical_name(written: str, name: str) -> None:
    assert canonical(written) == name


def test_display_names_and_known_names() -> None:
    assert display("postgres") == "PostgreSQL"
    assert display("Temporal") == "Temporal"
    assert is_known("k8s")
    assert not is_known("Temporal")
    assert canonical_set(["Postgres", "PostgreSQL", " ", "Kafka"]) == {"postgresql", "kafka"}
    assert "psql" in spellings("Postgres")
    assert spellings("Temporal") == ("Temporal",)


def names(text: str, extra: tuple[str, ...] = ()) -> set[str]:
    return SkillLexicon(extra).names_in(text)


def test_skills_are_found_as_whole_tokens() -> None:
    assert names("Built services with Kafka, PostgreSQL and Redis.") == {"kafka", "postgresql", "redis"}
    assert names("Kafka-based pipelines; (Docker) and k8s/Terraform.") == {"kafka", "docker", "kubernetes", "terraform"}
    assert names("We use Kafkaesque processes and Dockerfiles") == set()
    assert names("JavaScript is not Java") == {"javascript", "java"}


def test_names_with_symbols_are_found() -> None:
    assert names("Worked with C#, C++ and .NET; also Node.js.") == {"c#", "c++", ".net", "node.js"}
    assert names("ASP.NET Core services") == {".net"}
    assert names("CI/CD with GitHub Actions") == {"ci/cd", "github actions"}
    assert names("Next.js front ends") == {"next.js"}


def test_a_file_name_is_not_a_skill() -> None:
    assert names("see Main.java, app.py and server.go") == set()


def test_the_longest_name_wins() -> None:
    assert names("Spring Boot services") == {"spring boot"}
    assert names("SQL Server and SQL") == {"sql server", "sql"}
    assert names("React.js apps") == {"react"}


def test_everyday_words_are_not_skills_unless_written_as_the_name() -> None:
    assert names("We go to market in spring and react fast; take a rest.") == set()
    assert names("Go services on Spring with a REST API") == {"go", "spring", "rest"}
    assert names("a three-node cluster") == set()
    assert names("Node and Express") == {"node.js", "express"}
    assert names("the ml team builds ML models") == {"machine learning"}
    assert names("restful services") == {"rest"}


def test_single_letter_names_are_not_looked_for_in_text() -> None:
    assert names("Series C funding and R&D") == set()
    assert canonical("C") == "c"
    assert canonical("R") == "r"


def test_names_of_the_person_or_the_job_join_the_lexicon() -> None:
    assert names("Workflows on Temporal and temporal logic", ("Temporal",)) == {"temporal"}
    assert names("Workflows on Temporal") == set()
    assert names("Zapier automations", ("Zapier", "Postgres")) == {"zapier"}


def test_hits_carry_their_place_and_spelling() -> None:
    hits = SkillLexicon().find("Postgres then Kafka")

    assert [(h.name, h.surface, h.start) for h in hits] == [("postgresql", "Postgres", 0), ("kafka", "Kafka", 14)]


def test_arabic_text_around_a_name_does_not_hide_it() -> None:
    assert names("خبرة في Kafka وPostgreSQL") == {"kafka", "postgresql"}


def test_normalize_makes_small_differences_disappear() -> None:
    assert normalize("  “Smart”  quotes — and\tspaces ") == '"smart" quotes - and spaces'
    assert normalize("ＡＢＣ ٣ سنوات") == "abc 3 سنوات"
    assert western_digits("٩٣٪ و ۱۲") == "93٪ و 12"


def test_contains_compares_after_normalization() -> None:
    posting = "You have 3+ years’ experience\n  with   Kafka."

    assert contains(posting, "3+ years' experience with kafka")
    assert not contains(posting, "5+ years")
    assert not contains(posting, "   ")


def test_arabic_share() -> None:
    assert arabic_share("خبرة في Kafka") > 0.4
    assert arabic_share("Experience with Kafka") == 0
    assert arabic_share("123 !") == 0


class TestTextFromOutside:
    def test_control_characters_and_reordering_marks_are_taken_out(self) -> None:
        hostile = "Backend\x1b[31m Engineer\x07 \u202egnisrever\u202c \x9b2J"
        # What is left is harmless text: the characters that made it a command are gone.
        assert without_unseen(hostile) == "Backend[31m Engineer gnisrever 2J"
        assert has_unseen(hostile)
        assert not has_unseen(without_unseen(hostile))

    def test_line_breaks_tabs_and_arabic_stay(self) -> None:
        text = "سطر أول\nline two\twith a tab\r\nline three\rline four ‏"
        assert without_unseen(text) == "سطر أول\nline two\twith a tab\nline three\nline four ‏"
        assert not has_unseen("سطر أول\nline two\twith a tab")

    def test_a_name_from_outside_loses_what_markdown_would_act_on(self) -> None:
        assert plain_name("Tamween") == "Tamween"
        assert plain_name("Al-Futtaim & Sons, Ltd.") == "Al-Futtaim & Sons, Ltd."
        assert plain_name("[Evil](https://evil.test) <b>Co</b> `x` | # *big*") == "Evil https evil.test b Co /b x big"
        assert plain_name("  Many   spaces \x1b[0m ") == "Many spaces 0m"
