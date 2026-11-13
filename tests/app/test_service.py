"""The use cases on a real database and real files, with a scripted model."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from masar.app.errors import AppError, CareerInvalid, DailyLimit, NoModel, NotFound, Refused
from masar.domain.applications import Attention, State
from masar.domain.claims import DocumentKind
from masar.domain.job import Posting, Source
from masar.domain.matching import Recommendation
from masar.ports.files import FileProblem
from masar.ports.model import ModelUnavailable
from masar.ports.sources import Board
from tests.support.postings import TEXT, all_supported, assessment, cover_blocks, cv_blocks, extraction
from tests.support.world import World


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    made = World(tmp_path / "masar")
    yield made
    made.close()


def assessed(world: World) -> int:
    posting_id = world.add()
    world.script(extraction(), assessment())
    world.app.assess(posting_id)
    return posting_id


def pending_cv(world: World) -> tuple[int, int]:
    posting_id = assessed(world)
    world.script(cv_blocks(), all_supported(0, 1, 2, 3))
    return posting_id, world.app.draft(posting_id, DocumentKind.CV).document.id


class TestProfile:
    def test_a_good_file_reports_years_and_skills(self, world: World) -> None:
        report = world.app.profile()
        assert report.ok
        assert report.years == 5.5
        assert report.facts == 8
        assert "Kafka" in report.skills
        assert len(report.checksum) == 64

    def test_a_file_with_faults_reports_them(self, world: World) -> None:
        world.edit_career("id: acme-allocation", "id: Not An Id")
        report = world.app.profile()
        assert not report.ok
        assert report.years is None
        assert any(f.code == "CAREER-ID" for f in report.errors)

    def test_use_cases_that_need_the_career_refuse_a_file_with_faults(self, world: World) -> None:
        posting_id = world.add()
        world.edit_career("id: acme-allocation", "id: Not An Id")
        with pytest.raises(CareerInvalid) as error:
            world.app.assess(posting_id)
        assert error.value.findings
        assert world.model.calls == []

    def test_a_missing_file_is_a_file_problem(self, world: World) -> None:
        world.career_path.unlink()
        with pytest.raises(FileProblem, match="no such file"):
            world.app.profile()

    def test_the_facts_are_listed_without_the_person(self, world: World) -> None:
        facts = world.app.list_facts()
        assert [f.id for f in facts][:2] == ["acme-allocation", "acme-receiving"]
        assert facts[0].period == "2023-03 to present"
        shown = str(facts)
        for secret in ("Sara", "Al-Najjar", "sara@example.com", "+20 100", "github.com"):
            assert secret not in shown


class TestPostings:
    def test_a_pasted_posting_is_saved_once(self, world: World) -> None:
        stored, created = world.app.add_posting("  Tamween ", "Backend   Engineer", TEXT, " https://x.test ", "")
        again, created_again = world.app.add_posting("Tamween", "Backend Engineer", TEXT)

        assert (created, created_again) == (True, False)
        assert again.id == stored.id
        assert (stored.posting.company, stored.posting.title) == ("Tamween", "Backend Engineer")
        assert (stored.posting.url, stored.posting.location, stored.posting.source) == (
            "https://x.test",
            None,
            Source.MANUAL,
        )

    @pytest.mark.parametrize(
        ("company", "title", "text", "message"),
        [("", "T", "x", "company and a title"), ("C", " ", "x", "company and a title"), ("C", "T", "  ", "no text")],
    )
    def test_an_empty_posting_is_refused(self, world: World, company: str, title: str, text: str, message: str) -> None:
        with pytest.raises(AppError, match=message):
            world.app.add_posting(company, title, text)

    def test_a_huge_posting_is_refused(self, world: World) -> None:
        with pytest.raises(AppError, match="longer than 200000"):
            world.app.add_posting("C", "T", "x" * 200_001)

    def test_an_unknown_job_is_not_found(self, world: World) -> None:
        with pytest.raises(NotFound, match="no job 77"):
            world.app.job(77)


class TestFetch:
    TAMWEEN = Board(Source.GREENHOUSE, "tamween", "Tamween")
    QAFILA = Board(Source.LEVER, "qafila", "Qafila")

    def watch(self, world: World) -> None:
        world.watchlist_path.write_text(
            "boards:\n  - {source: greenhouse, board: tamween, company: Tamween}\n  - {source: lever, board: qafila, company: Qafila}\n",
            encoding="utf-8",
        )

    def posting(self, title: str, n: int) -> Posting:
        return Posting(Source.GREENHOUSE, "Tamween", title, f"Text number {n}.", external_id=f"tamween:{n}")

    def test_new_postings_are_kept_when_their_title_passes(self, world: World) -> None:
        self.watch(world)
        world.boards.serve(
            self.TAMWEEN,
            self.posting("Backend Engineer", 1),
            self.posting("Sales Manager", 2),
            self.posting("Senior Software Engineer", 3),
            self.posting("Backend Engineering Intern", 4),
            skipped=2,
        )
        first, second = world.app.fetch()

        assert (first.new, first.known, first.filtered, first.skipped, first.error) == (2, 0, 2, 2, None)
        assert (second.new, second.error) == (0, "HTTP 404")  # one board failing does not stop the other
        assert [b.board for b in world.boards.asked] == ["tamween", "qafila"]
        assert sorted(j.title for j in world.app.list_jobs()) == ["Backend Engineer", "Senior Software Engineer"]

    def test_a_second_fetch_finds_nothing_new(self, world: World) -> None:
        self.watch(world)
        world.boards.serve(self.TAMWEEN, self.posting("Backend Engineer", 1))
        world.app.fetch()
        first, _ = world.app.fetch()
        assert (first.new, first.known) == (0, 1)
        assert len(world.app.list_jobs()) == 1

    def test_a_watchlist_with_faults_stops_before_any_request(self, world: World) -> None:
        world.watchlist_path.write_text("boards:\n  - {source: linkedin, board: x}\n", encoding="utf-8")
        with pytest.raises(AppError, match=r"boards\[0\]"):
            world.app.fetch()
        assert world.boards.asked == []

    def test_no_watchlist_is_a_file_problem(self, world: World) -> None:
        with pytest.raises(FileProblem):
            world.app.fetch()

    def test_fetching_asks_no_model(self, world: World) -> None:
        self.watch(world)
        world.boards.serve(self.TAMWEEN, self.posting("Backend Engineer", 1))
        world.app.fetch()
        assert world.model.calls == []


class TestAssess:
    def test_a_posting_is_assessed_and_everything_is_kept(self, world: World) -> None:
        posting_id = world.add()
        world.script(extraction(), assessment())
        result = world.app.assess(posting_id)

        assert (result.record.status, result.record.score, result.reason) == ("assessed", 90, None)
        assert result.record.recommendation is Recommendation.APPLY
        detail = world.app.job(posting_id)
        assert detail.job == result.record
        assert detail.stale is False
        assert detail.application.state is State.FOUND

        run, steps = world.app.run(result.run_id)
        assert (run.kind, run.status, run.posting_id) == ("intake", "done", posting_id)
        assert [s.step for s in steps] == ["extract", "assess"]
        assert run.tokens_in + run.tokens_out == world.app.tokens_today()[0] > 0

        (summary,) = world.app.list_jobs()
        assert (summary.status, summary.score) == ("assessed", 90)

    def test_changing_the_career_file_marks_the_assessment_as_stale(self, world: World) -> None:
        posting_id = assessed(world)
        world.edit_career("headline: Backend engineer", "headline: Platform engineer")
        assert world.app.job(posting_id).stale is True

    def test_a_failed_run_is_kept_as_failed_with_its_reason_and_its_tokens(self, world: World) -> None:
        posting_id = world.add()
        world.script(extraction(), ModelUnavailable("HTTP 503"))
        result = world.app.assess(posting_id)

        assert result.record.status == "failed"
        assert result.reason == "model unavailable: HTTP 503"
        run, steps = world.app.run(result.run_id)
        assert (run.status, run.reason) == ("failed", "model unavailable: HTTP 503")
        assert [s.step for s in steps] == ["extract"]  # what was spent is still counted
        assert world.app.tokens_today()[0] == steps[0].tokens_in + steps[0].tokens_out

    def test_output_that_cannot_be_read_is_a_failed_run(self, world: World) -> None:
        posting_id = world.add()
        world.script("no", "no again")
        result = world.app.assess(posting_id)
        assert result.record.status == "failed"
        assert (result.reason or "").startswith("model output:")

    def test_a_failed_job_can_be_assessed_again(self, world: World) -> None:
        posting_id = world.add()
        world.script("no", "no again", extraction(), assessment())
        world.app.assess(posting_id)
        assert world.app.assess(posting_id).record.score == 90

    def test_without_a_model_it_says_what_to_set(self, tmp_path: Path) -> None:
        bare = World(tmp_path / "bare", with_model=False)
        try:
            posting_id = bare.add()
            with pytest.raises(NoModel, match="MASAR_LLM_PROVIDER"):
                bare.app.assess(posting_id)
            assert bare.app.runs() == []
        finally:
            bare.close()

    def test_the_daily_limit_stops_a_run_before_it_starts(self, tmp_path: Path) -> None:
        big = World(tmp_path / "home")
        first, second = big.add(), big.add("Other", "Backend Engineer", TEXT + " More.")
        big.script(extraction(), assessment())
        big.app.assess(first)
        used, _ = big.app.tokens_today()
        big.close()

        # The same folder, with a limit that today's use has just reached.
        small = World(tmp_path / "home", daily_tokens=used)
        small._ids = big._ids
        try:
            small.script(extraction(), assessment())
            with pytest.raises(DailyLimit, match="starts again tomorrow"):
                small.app.assess(second)
            assert small.model.calls == []
            assert len(small.app.runs()) == 1  # no run was started for it

            small.clock.advance(24 * 3600)  # a new day
            assert small.app.assess(second).record.status == "assessed"
        finally:
            small.close()

    def test_a_run_gets_no_more_tokens_than_the_day_has_left(self, tmp_path: Path) -> None:
        small = World(tmp_path / "small", daily_tokens=450)
        try:
            posting_id = small.add()
            small.script(extraction(), assessment())
            result = small.app.assess(posting_id)
            assert result.record.status == "failed"
            assert result.reason == "budget: the run used up its tokens"
        finally:
            small.close()

    def test_all_new_postings_are_assessed_oldest_first(self, world: World) -> None:
        first = world.add()
        second = world.add("Qafila", "Backend Engineer", TEXT + " Second.")
        third = assessed_id = world.add("Sanad", "Backend Engineer", TEXT + " Third.")
        world.script(extraction(), assessment())
        world.app.assess(assessed_id)
        world.script(extraction(), assessment(), extraction(), assessment())

        results = world.app.assess_new()
        assert [r.posting_id for r in results] == [first, second]
        assert third not in [r.posting_id for r in results]
        assert world.app.list_jobs(status="new") == []

    def test_assessing_all_stops_when_the_provider_is_down(self, world: World) -> None:
        world.add()
        world.add("Qafila", "Backend Engineer", TEXT + " Second.")
        world.script(ModelUnavailable("HTTP 503"), extraction(), assessment())
        results = world.app.assess_new()
        assert len(results) == 1
        assert len(world.model.calls) == 1

    def test_assessing_all_goes_on_after_one_unreadable_answer(self, world: World) -> None:
        world.add()
        world.add("Qafila", "Backend Engineer", TEXT + " Second.")
        world.script("no", "no again", extraction(), assessment())
        results = world.app.assess_new()
        assert [r.record.status for r in results] == ["failed", "assessed"]


class TestDraft:
    def test_a_draft_waits_for_the_person(self, world: World) -> None:
        posting_id, document_id = pending_cv(world)
        document = world.app.get_draft(document_id)

        assert (document.status, document.kind, document.language) == ("pending", DocumentKind.CV, "en")
        assert (document.judged, document.edited, document.decided_at) == (True, False, None)
        assert document.markdown.startswith("# Sara Al-Najjar")
        run, steps = world.app.run(document.run_id)
        assert (run.kind, run.status) == ("tailor", "waiting")
        assert [s.step for s in steps] == ["draft", "judge"]
        assert world.app.job(posting_id).application.state is State.FOUND  # a draft alone moves nothing
        assert [d.id for d in world.app.list_drafts("pending")] == [document_id]

    def test_a_job_must_be_read_before_it_is_drafted_for(self, world: World) -> None:
        posting_id = world.add()
        with pytest.raises(AppError, match=f"masar assess {posting_id}"):
            world.app.draft(posting_id, DocumentKind.CV)
        assert world.model.calls == []

    def test_only_known_languages(self, world: World) -> None:
        posting_id = assessed(world)
        with pytest.raises(AppError, match="en, ar"):
            world.app.draft(posting_id, DocumentKind.CV, "fr")

    def test_a_draft_that_fails_is_kept_as_failed_with_its_reason(self, world: World) -> None:
        posting_id = assessed(world)
        letter = cover_blocks()
        letter["blocks"][1]["text"] = "At Acme Retail I led a team of 12 engineers."
        letter["blocks"][2]["text"] = "I am an expert in Rust."
        world.script(letter, all_supported(0), {"repairs": []}, {"repairs": []})
        document = world.app.draft(posting_id, DocumentKind.COVER).document

        assert document.status == "failed"
        assert "only 1 of the needed 2 paragraphs" in (document.reason or "")
        run, _ = world.app.run(document.run_id)
        assert run.status == "failed"
        with pytest.raises(Refused, match="is failed"):
            world.app.decide(document.id, "approve")

    def test_a_provider_failure_gives_a_failed_draft_not_an_exception(self, world: World) -> None:
        posting_id = assessed(world)
        world.script(ModelUnavailable("HTTP 500"))
        document = world.app.draft(posting_id, DocumentKind.CV).document
        assert (document.status, document.reason) == ("failed", "model unavailable: HTTP 500")

    def test_a_screened_out_job_can_still_be_drafted_for(self, world: World) -> None:
        world.edit_career("countries: [SA, AE, EG]", "countries: [AE]")
        posting_id = world.add()
        world.script(extraction())
        assert world.app.assess(posting_id).record.status == "screened"
        world.script(cv_blocks(), all_supported(0, 1, 2, 3))
        assert world.app.draft(posting_id, DocumentKind.CV).document.status == "pending"


class TestDecide:
    def test_approving_marks_the_document_and_moves_the_application(self, world: World) -> None:
        posting_id, document_id = pending_cv(world)
        calls = len(world.model.calls)
        world.clock.advance(3600)
        result = world.app.decide(document_id, "approve")

        assert (result.document.status, result.problem, result.moved_to_drafted) == ("approved", None, True)
        assert result.document.decided_at == world.clock.now()
        assert world.app.get_draft(document_id) == result.document
        assert world.app.job(posting_id).application.state is State.DRAFTED
        history = world.app.history(posting_id)
        assert (history[-1].from_state, history[-1].to_state, history[-1].note) == (
            State.FOUND,
            State.DRAFTED,
            "a document was approved",
        )
        assert world.app.run(result.document.run_id)[0].status == "done"
        assert len(world.model.calls) == calls  # a decision asks no model

    def test_rejecting_moves_nothing(self, world: World) -> None:
        posting_id, document_id = pending_cv(world)
        result = world.app.decide(document_id, "reject")
        assert (result.document.status, result.moved_to_drafted) == ("rejected", False)
        assert world.app.job(posting_id).application.state is State.FOUND

    def test_a_decided_draft_cannot_be_decided_again(self, world: World) -> None:
        _, document_id = pending_cv(world)
        world.app.decide(document_id, "reject")
        with pytest.raises(Refused, match="is rejected"):
            world.app.decide(document_id, "approve")
        assert world.app.get_draft(document_id).status == "rejected"

    def test_an_unknown_draft(self, world: World) -> None:
        with pytest.raises(NotFound):
            world.app.decide(5, "approve")

    def test_a_draft_is_approved_after_a_restart(self, world: World, request: pytest.FixtureRequest) -> None:
        posting_id, document_id = pending_cv(world)
        again = world.restart()
        request.addfinalizer(again.close)

        result = again.app.decide(document_id, "approve")
        assert result.document.status == "approved"
        assert again.app.job(posting_id).application.state is State.DRAFTED
        assert again.model.calls == []

    def test_an_edit_is_checked_and_kept_and_can_then_be_approved(self, world: World) -> None:
        _, document_id = pending_cv(world)
        blocks = cv_blocks()["blocks"]
        blocks[0]["text"] = "Backend engineer with 5 years of experience on Kafka and PostgreSQL."
        blocks.append({"section": "summary", "kind": "claim", "text": "Expert in Rust.", "facts": ["acme-allocation"]})
        result = world.app.decide(document_id, "edit", blocks)

        document = world.app.get_draft(document_id)
        assert document == result.document
        assert (document.status, document.edited, document.judged, document.decided_at) == (
            "pending",
            True,
            False,
            None,
        )
        assert "with 5 years of experience on Kafka and PostgreSQL." in document.markdown
        assert [d.text for d in document.dropped] == ["Expert in Rust."]
        assert world.app.decide(document_id, "approve").document.status == "approved"

    def test_an_edit_that_cannot_be_used_leaves_the_draft_as_it_was(self, world: World) -> None:
        _, document_id = pending_cv(world)
        before = world.app.get_draft(document_id)
        result = world.app.decide(document_id, "edit", "one long text")
        assert "edit refused" in (result.problem or "")
        assert world.app.get_draft(document_id) == before

    def test_approval_is_refused_when_the_career_file_no_longer_supports_the_draft(self, world: World) -> None:
        posting_id, document_id = pending_cv(world)
        world.edit_career("that raised store availability to 93%.", "that raised store availability.")
        result = world.app.decide(document_id, "approve")

        assert result.document.status == "pending"
        assert "UNSUPPORTED_NUMBER: 93" in (result.problem or "")
        assert world.app.get_draft(document_id).status == "pending"
        assert world.app.job(posting_id).application.state is State.FOUND

    def test_an_approved_document_does_not_move_an_application_that_is_further_on(self, world: World) -> None:
        posting_id, document_id = pending_cv(world)
        world.app.move_application(posting_id, "shortlisted")
        world.app.move_application(posting_id, "applied")
        result = world.app.decide(document_id, "approve")
        assert (result.document.status, result.moved_to_drafted) == ("approved", False)
        assert world.app.job(posting_id).application.state is State.APPLIED

    def test_a_decision_that_was_taken_but_not_written_is_picked_up(self, world: World) -> None:
        """The process stopped after the flow ended and before the draft was updated."""
        from masar.agent.prompts import PROMPT_VERSION
        from masar.agent.session import ModelSession, NoModel
        from masar.agent.tailor import TailorDeps, build_tailor_graph, resume_tailor
        from tests.support.career import example_career

        posting_id, document_id = pending_cv(world)
        run_id = world.app.get_draft(document_id).run_id
        deps = TailorDeps(
            ModelSession(NoModel(), world.clock, PROMPT_VERSION), example_career(), world.clock.now().date()
        )
        resume_tailor(build_tailor_graph(deps, world.checkpointer), run_id, {"action": "approve"})
        assert world.app.get_draft(document_id).status == "pending"

        result = world.app.decide(document_id, "reject")  # whatever is asked now, the flow said "approved"
        assert result.document.status == "approved"
        assert world.app.job(posting_id).application.state is State.DRAFTED

    def test_only_an_approved_document_may_leave(self, world: World) -> None:
        _, document_id = pending_cv(world)
        with pytest.raises(Refused, match="only an approved document is exported"):
            world.app.approved_document(document_id)
        world.app.decide(document_id, "approve")
        document, posting = world.app.approved_document(document_id)
        assert (document.status, posting.posting.company) == ("approved", "Tamween")


class TestApplications:
    def test_the_person_moves_an_application_with_a_note(self, world: World) -> None:
        posting_id = world.add()
        moved = world.app.move_application(posting_id, " Shortlisted ", "  good   fit ")
        assert moved.state is State.SHORTLISTED
        assert world.app.history(posting_id)[-1].note == "good fit"
        assert [(a.state, p.posting.company) for a, p in world.app.applications()] == [(State.SHORTLISTED, "Tamween")]

    def test_a_move_that_is_not_allowed_is_refused_with_the_options(self, world: World) -> None:
        posting_id = world.add()
        with pytest.raises(Refused, match="from 'found' you can move to: shortlisted, skipped"):
            world.app.move_application(posting_id, "offer")

    def test_the_person_cannot_set_drafted(self, world: World) -> None:
        posting_id = world.add()
        with pytest.raises(Refused, match="set by Masar when you approve"):
            world.app.move_application(posting_id, "drafted")

    def test_a_word_that_is_not_a_state(self, world: World) -> None:
        posting_id = world.add()
        with pytest.raises(AppError, match="'hired' is not a state"):
            world.app.move_application(posting_id, "hired")

    def test_an_unknown_job(self, world: World) -> None:
        with pytest.raises(NotFound):
            world.app.move_application(9, "skipped")
        with pytest.raises(NotFound):
            world.app.history(9)


class TestToday:
    def test_a_waiting_draft_and_a_quiet_application_need_attention(self, world: World) -> None:
        _, document_id = pending_cv(world)
        quiet = world.add("Qafila", "Platform Engineer", TEXT + " Other.")
        world.app.move_application(quiet, "shortlisted")
        world.app.move_application(quiet, "applied")
        fresh = world.add("Sanad", "AI Engineer", TEXT + " Third.")
        world.app.move_application(fresh, "shortlisted")

        world.clock.advance(11 * 24 * 3600)
        items = world.app.today()
        assert [(i.company, i.reason, i.days) for i in items] == [
            ("Tamween", Attention.DRAFT_WAITING, 11),
            ("Sanad", Attention.NO_DRAFT, 11),
            ("Qafila", Attention.APPLIED_QUIET, 11),
        ]

        world.app.decide(document_id, "approve")
        assert Attention.DRAFT_WAITING not in [i.reason for i in world.app.today()]

    def test_nothing_to_do(self, world: World) -> None:
        world.add()
        assert world.app.today() == []


class TestRuns:
    def test_a_run_is_found_by_the_start_of_its_id(self, world: World) -> None:
        assessed(world)
        (run,) = world.app.runs()
        assert world.app.run("run-00")[0].id == run.id
        with pytest.raises(NotFound):
            world.app.run("run-9")
        with pytest.raises(NotFound):
            world.app.run("r")


class TestCheckClaims:
    def test_an_honest_sentence_passes(self, world: World) -> None:
        text = "I built an inventory allocation service on Kafka that raised store availability to 93%."
        assert world.app.check_claims(text, ["acme-allocation"]) == []

    def test_a_false_skill_and_number_are_named(self, world: World) -> None:
        found = world.app.check_claims(
            "I built it in Rust and cut costs by 40%.", ["acme-allocation", "acme-allocation"]
        )
        assert [(v.code, v.detail) for v in found] == [("UNSUPPORTED_SKILL", "Rust"), ("UNSUPPORTED_NUMBER", "40")]

    def test_a_sentence_with_no_fact_is_a_claim_without_a_fact(self, world: World) -> None:
        assert [v.code for v in world.app.check_claims("I am a strong engineer.", [])] == ["CLAIM_WITHOUT_FACT"]

    def test_the_job_gives_the_context(self, world: World) -> None:
        posting_id = assessed(world)
        text = "As a Backend Engineer at Tamween I would bring my work on Kafka."
        assert world.app.check_claims(text, ["acme-allocation"], posting_id=posting_id) == []
        # Kubernetes is asked for by this job, so it is looked for, and no fact has it.
        found = world.app.check_claims("I ran Kubernetes clusters.", ["acme-allocation"], posting_id=posting_id)
        assert [(v.code, v.detail) for v in found] == [("UNSUPPORTED_SKILL", "Kubernetes")]

    def test_arabic_is_checked_as_arabic(self, world: World) -> None:
        found = world.app.check_claims("I built a service on Kafka.", ["acme-allocation"], language="ar")
        assert [v.code for v in found] == ["WRONG_LANGUAGE"]
        with pytest.raises(AppError):
            world.app.check_claims("x", [], language="de")


class TestEdges:
    def test_a_draft_whose_run_is_gone_cannot_be_decided(self, world: World) -> None:
        _, document_id = pending_cv(world)
        orphan = replace(world.app.get_draft(document_id), run_id="a-run-nobody-knows")
        orphan_id = world.store.add_document(orphan)
        with pytest.raises(AppError, match="cannot be continued; draft it again"):
            world.app.decide(orphan_id, "approve")
        assert world.app.get_draft(orphan_id).status == "pending"

    def test_a_draft_decided_by_another_process_in_the_same_moment_is_refused(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        posting_id, document_id = pending_cv(world)
        monkeypatch.setattr(world.store, "update_pending_document", lambda record: False)
        with pytest.raises(Refused, match="decided in the meantime"):
            world.app.decide(document_id, "approve")
        assert world.app.job(posting_id).application.state is State.FOUND  # nothing moved on a lost race

    def test_an_application_moved_by_another_process_in_the_same_moment_is_refused(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        posting_id = world.add()
        monkeypatch.setattr(world.store, "move_application", lambda *args: False)
        with pytest.raises(Refused, match="moved in the meantime"):
            world.app.move_application(posting_id, "shortlisted")

    def test_a_missing_career_file_does_not_break_looking_at_a_job(self, world: World) -> None:
        posting_id = assessed(world)
        world.career_path.unlink()
        assert world.app.job(posting_id).stale is False

    def test_assessing_all_stops_quietly_when_the_day_runs_out_on_the_way(self, tmp_path: Path) -> None:
        probe = World(tmp_path / "probe")
        probe.add()
        probe.script(extraction(), assessment())
        probe.app.assess(1)
        one_run, _ = probe.app.tokens_today()
        probe.close()

        small = World(tmp_path / "small", daily_tokens=one_run)
        try:
            small.add()
            small.add("Qafila", "Backend Engineer", TEXT + " Second.")
            small.script(extraction(), assessment(), extraction(), assessment())
            results = small.app.assess_new()
            assert [r.record.status for r in results] == ["assessed"]
            assert len(small.app.list_jobs(status="new")) == 1
            with pytest.raises(DailyLimit):
                small.app.assess_new()  # nothing at all could be done this time
        finally:
            small.close()

    def test_fetching_needs_job_boards(self, world: World) -> None:
        world.app._boards = None
        with pytest.raises(AppError, match="no job boards"):
            world.app.fetch()

    def test_the_title_of_the_job_is_not_a_claim_about_the_person(self, world: World) -> None:
        posting_id = world.add(title="Senior Backend Engineer")
        world.script(extraction(), assessment())
        world.app.assess(posting_id)
        text = "For the Senior Backend Engineer role I bring my work on Kafka."
        assert world.app.check_claims(text, ["acme-allocation"], posting_id=posting_id) == []
        without = world.app.check_claims(text, ["acme-allocation"])
        assert [(v.code, v.detail) for v in without] == [("UNSUPPORTED_TITLE", "senior")]
