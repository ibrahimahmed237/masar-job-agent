"""The store on a real SQLite file: every table, the rules of the design, and two processes on one file."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from masar.adapters import sqlite_store
from masar.adapters.checkpoint import open_checkpointer
from masar.adapters.sqlite_store import SqliteStore, migrations
from masar.domain.applications import State
from masar.domain.claims import Block, BlockKind, DocumentKind, Section
from masar.domain.document import DroppedBlock
from masar.domain.findings import Finding
from masar.domain.job import Posting, Source
from masar.domain.matching import Assessment, Flag, FlagSeverity, Recommendation, RequirementAssessment, Verdict
from masar.ports.store import DocumentRecord, JobRecord, RunStep
from tests.support.jobs import example_job
from tests.support.postings import example_posting

AT = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "masar.db"


@pytest.fixture
def store(path: Path) -> Iterator[SqliteStore]:
    opened = SqliteStore(path)
    yield opened
    opened.close()


def job_record(posting_id: int, **changes: object) -> JobRecord:
    record = JobRecord(
        posting_id=posting_id,
        status="assessed",
        job=example_job(),
        findings=(Finding.warning("JOB-SKILL", "requirements[0]", "dropped"),),
        flags=(Flag("YEARS_BELOW", FlagSeverity.WARNING, "a little short"),),
        assessment=Assessment((RequirementAssessment("r1", Verdict.PARTIAL, ("a",), "n", "code", Verdict.MET, "why"),)),
        score=83,
        recommendation=Recommendation.APPLY,
        career_checksum="c" * 64,
        assessed_at=AT,
    )
    return replace(record, **changes)  # type: ignore[arg-type]


def document(posting_id: int, **changes: object) -> DocumentRecord:
    record = DocumentRecord(
        id=0,
        posting_id=posting_id,
        kind=DocumentKind.COVER,
        language="en",
        status="pending",
        markdown="Dear team,\n\nنص\n",
        blocks=(Block(Section.BODY, BlockKind.CLAIM, "I built it.", ("acme-allocation",)),),
        dropped=(DroppedBlock("Bad.", ("UNSUPPORTED_SKILL: Rust",)),),
        warnings=("not judged: x",),
        judged=False,
        edited=False,
        reason=None,
        run_id="run-1",
        career_checksum="c" * 64,
        created_at=AT,
        decided_at=None,
    )
    return replace(record, **changes)  # type: ignore[arg-type]


class TestPostings:
    def test_a_posting_is_saved_and_read_back(self, store: SqliteStore) -> None:
        posting = Posting(
            Source.LEVER, "Qafila", "Platform Engineer", "Text ـ نص", "https://x.test/1", "Dubai", "qafila:1"
        )
        stored, created = store.add_posting(posting, AT)

        assert created is True
        assert stored.posting == posting
        assert stored.fetched_at == AT
        assert store.get_posting(stored.id) == stored
        assert store.get_posting(999) is None

    def test_the_same_content_is_one_posting(self, store: SqliteStore) -> None:
        first, _ = store.add_posting(example_posting(), AT)
        again, created = store.add_posting(replace(example_posting(), url="https://other.test"), AT + timedelta(days=1))

        assert created is False
        assert again == first  # the first one is kept as it was
        assert len(store.list_jobs()) == 1

    def test_the_same_board_id_is_one_posting_even_when_the_text_changed(self, store: SqliteStore) -> None:
        posting = Posting(Source.GREENHOUSE, "Tamween", "Backend Engineer", "First text.", external_id="tamween:1")
        store.add_posting(posting, AT)
        again, created = store.add_posting(replace(posting, text="Changed text."), AT)

        assert created is False
        assert again.posting.text == "First text."

    def test_the_same_id_on_another_source_is_another_posting(self, store: SqliteStore) -> None:
        store.add_posting(Posting(Source.GREENHOUSE, "A", "T", "Text one.", external_id="x:1"), AT)
        _, created = store.add_posting(Posting(Source.LEVER, "A", "T", "Text two.", external_id="x:1"), AT)
        assert created is True

    def test_pasted_postings_have_no_board_id_and_do_not_collide(self, store: SqliteStore) -> None:
        store.add_posting(Posting(Source.MANUAL, "A", "T", "Text one."), AT)
        _, created = store.add_posting(Posting(Source.MANUAL, "A", "T", "Text two."), AT)
        assert created is True

    def test_a_new_posting_starts_an_application_as_found(self, store: SqliteStore) -> None:
        stored, _ = store.add_posting(example_posting(), AT)
        application = store.get_application(stored.id)

        assert application is not None
        assert application.state is State.FOUND
        (event,) = store.application_events(stored.id)
        assert (event.from_state, event.to_state, event.at) == (None, State.FOUND, AT)


class TestJobs:
    def test_a_job_is_saved_and_read_back_whole(self, store: SqliteStore) -> None:
        stored, _ = store.add_posting(example_posting(), AT)
        record = job_record(stored.id)
        store.save_job(record)
        assert store.get_job(stored.id) == record

    def test_an_unreadable_posting_is_kept_with_its_findings(self, store: SqliteStore) -> None:
        stored, _ = store.add_posting(example_posting(), AT)
        record = job_record(
            stored.id, status="unreadable", job=None, assessment=None, score=None, recommendation=None, flags=()
        )
        store.save_job(record)
        assert store.get_job(stored.id) == record

    def test_a_later_run_replaces_the_earlier_one(self, store: SqliteStore) -> None:
        stored, _ = store.add_posting(example_posting(), AT)
        store.save_job(job_record(stored.id))
        store.save_job(job_record(stored.id, score=40, recommendation=Recommendation.SKIP))

        read = store.get_job(stored.id)
        assert read is not None
        assert (read.score, read.recommendation) == (40, Recommendation.SKIP)

    def test_a_status_outside_the_list_is_refused(self, store: SqliteStore) -> None:
        stored, _ = store.add_posting(example_posting(), AT)
        with pytest.raises(sqlite3.IntegrityError):
            store.save_job(job_record(stored.id, status="approved"))

    def test_a_job_needs_its_posting(self, store: SqliteStore) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            store.save_job(job_record(12345))

    def test_the_list_shows_new_postings_and_sorts_by_score(self, store: SqliteStore) -> None:
        ids = [
            store.add_posting(Posting(Source.MANUAL, f"Co{i}", "Engineer", f"Text {i}."), AT)[0].id for i in range(4)
        ]
        store.save_job(job_record(ids[0], score=55, recommendation=Recommendation.MAYBE))
        store.save_job(job_record(ids[1], score=90))
        store.save_job(
            job_record(ids[2], status="screened", score=None, recommendation=Recommendation.SKIP, assessment=None)
        )

        listed = store.list_jobs()
        assert [(j.posting_id, j.status, j.score) for j in listed] == [
            (ids[1], "assessed", 90),
            (ids[0], "assessed", 55),
            (ids[3], "new", None),
            (ids[2], "screened", None),
        ]
        assert listed[0].flags == (Flag("YEARS_BELOW", FlagSeverity.WARNING, "a little short"),)
        assert listed[2].flags == ()
        assert listed[0].state is State.FOUND
        assert listed[0].company == "Co1"

    def test_the_list_filters_by_status_and_score(self, store: SqliteStore) -> None:
        ids = [
            store.add_posting(Posting(Source.MANUAL, f"Co{i}", "Engineer", f"Text {i}."), AT)[0].id for i in range(3)
        ]
        store.save_job(job_record(ids[0], score=55))
        store.save_job(job_record(ids[1], score=90))

        assert [j.posting_id for j in store.list_jobs(status="new")] == [ids[2]]
        assert [j.posting_id for j in store.list_jobs(status="assessed")] == [ids[1], ids[0]]
        assert [j.posting_id for j in store.list_jobs(min_score=55)] == [ids[1], ids[0]]
        assert [j.posting_id for j in store.list_jobs(min_score=56)] == [ids[1]]


class TestDocuments:
    def test_a_draft_is_saved_and_read_back_whole(self, store: SqliteStore) -> None:
        stored, _ = store.add_posting(example_posting(), AT)
        document_id = store.add_document(document(stored.id))

        assert store.get_document(document_id) == document(stored.id, id=document_id)
        assert store.get_document(999) is None

    def test_drafts_are_listed_newest_first_and_filtered(self, store: SqliteStore) -> None:
        stored, _ = store.add_posting(example_posting(), AT)
        other, _ = store.add_posting(Posting(Source.MANUAL, "B", "T", "Other text."), AT)
        first = store.add_document(document(stored.id))
        second = store.add_document(document(stored.id, status="failed", reason="too short", markdown=""))
        third = store.add_document(document(other.id))

        assert [d.id for d in store.list_documents()] == [third, second, first]
        assert [d.id for d in store.list_documents(status="pending")] == [third, first]
        assert [d.id for d in store.list_documents(posting_id=stored.id)] == [second, first]
        assert store.list_documents(status="failed")[0].reason == "too short"

    def test_a_pending_draft_can_be_edited_and_then_decided_once(self, store: SqliteStore) -> None:
        stored, _ = store.add_posting(example_posting(), AT)
        document_id = store.add_document(document(stored.id))
        current = document(stored.id, id=document_id)

        edited = replace(current, markdown="New text", edited=True, warnings=("edited by hand",), dropped=())
        assert store.update_pending_document(edited) is True
        assert store.get_document(document_id) == edited

        approved = replace(edited, status="approved", decided_at=AT + timedelta(hours=1))
        assert store.update_pending_document(approved) is True
        assert store.get_document(document_id) == approved

        # Decided is decided: neither a second decision nor a late edit gets through.
        assert store.update_pending_document(replace(approved, status="rejected")) is False
        assert store.update_pending_document(replace(edited, markdown="Sneaky")) is False
        assert store.get_document(document_id) == approved

    def test_updating_a_draft_that_does_not_exist_changes_nothing(self, store: SqliteStore) -> None:
        stored, _ = store.add_posting(example_posting(), AT)
        assert store.update_pending_document(document(stored.id, id=404)) is False


class TestApplications:
    def test_a_move_changes_the_state_and_records_the_event(self, store: SqliteStore) -> None:
        stored, _ = store.add_posting(example_posting(), AT)
        later = AT + timedelta(days=2)

        assert store.move_application(stored.id, State.FOUND, State.SHORTLISTED, "looks good", later) is True
        application = store.get_application(stored.id)
        assert application is not None
        assert (application.state, application.updated_at) == (State.SHORTLISTED, later)
        events = store.application_events(stored.id)
        assert [(e.from_state, e.to_state, e.note) for e in events] == [
            (None, State.FOUND, None),
            (State.FOUND, State.SHORTLISTED, "looks good"),
        ]

    def test_a_move_from_a_state_the_application_is_not_in_does_nothing(self, store: SqliteStore) -> None:
        stored, _ = store.add_posting(example_posting(), AT)
        assert store.move_application(stored.id, State.SHORTLISTED, State.APPLIED, None, AT) is False
        application = store.get_application(stored.id)
        assert application is not None
        assert application.state is State.FOUND
        assert len(store.application_events(stored.id)) == 1

    def test_two_processes_cannot_both_move_the_same_application(self, store: SqliteStore, path: Path) -> None:
        stored, _ = store.add_posting(example_posting(), AT)
        second = SqliteStore(path)
        try:
            assert store.move_application(stored.id, State.FOUND, State.SHORTLISTED, None, AT) is True
            assert second.move_application(stored.id, State.FOUND, State.SKIPPED, None, AT) is False
            application = second.get_application(stored.id)
            assert application is not None
            assert application.state is State.SHORTLISTED
        finally:
            second.close()

    def test_times_from_other_zones_are_kept_as_utc_so_that_they_sort(self, store: SqliteStore) -> None:
        cairo = timezone(timedelta(hours=2))
        first, _ = store.add_posting(Posting(Source.MANUAL, "A", "T", "Text one."), AT)
        second, _ = store.add_posting(Posting(Source.MANUAL, "B", "T", "Text two."), AT)
        # 11:30 in Cairo is 09:30 UTC: earlier than 10:00 UTC, though its text would sort later.
        store.move_application(
            first.id, State.FOUND, State.SHORTLISTED, None, datetime(2026, 11, 13, 11, 30, tzinfo=cairo)
        )
        store.move_application(
            second.id, State.FOUND, State.SHORTLISTED, None, datetime(2026, 11, 13, 10, 0, tzinfo=UTC)
        )

        assert [a.posting_id for a in store.list_applications()] == [second.id, first.id]
        application = store.get_application(first.id)
        assert application is not None
        assert application.updated_at.utcoffset() == timedelta(0)

    def test_applications_are_listed_by_last_change(self, store: SqliteStore) -> None:
        first, _ = store.add_posting(Posting(Source.MANUAL, "A", "T", "Text one."), AT)
        second, _ = store.add_posting(Posting(Source.MANUAL, "B", "T", "Text two."), AT)
        store.move_application(first.id, State.FOUND, State.SHORTLISTED, None, AT + timedelta(days=1))
        assert [a.posting_id for a in store.list_applications()] == [first.id, second.id]
        assert store.get_application(999) is None


class TestRuns:
    STEP = RunStep("extract", "scripted", "v1", 100, 20, 1500, "a" * 64, '{"x": 1}')

    def test_a_run_is_started_finished_and_read_back_with_its_steps(self, store: SqliteStore) -> None:
        stored, _ = store.add_posting(example_posting(), AT)
        store.start_run("run-1", "intake", stored.id, AT)

        running = store.get_run("run-1")
        assert running is not None
        assert (running.status, running.ended_at, running.tokens_in) == ("running", None, 0)

        steps = [self.STEP, replace(self.STEP, step="assess", tokens_in=300, tokens_out=50)]
        store.finish_run("run-1", "done", None, steps, AT + timedelta(seconds=9))

        done = store.get_run("run-1")
        assert done is not None
        assert (done.status, done.reason, done.tokens_in, done.tokens_out) == ("done", None, 400, 70)
        assert done.ended_at == AT + timedelta(seconds=9)
        assert store.run_steps("run-1") == steps

    def test_a_run_that_waits_and_goes_on_keeps_all_its_steps_in_order(self, store: SqliteStore) -> None:
        store.start_run("run-2", "tailor", None, AT)
        store.finish_run("run-2", "waiting", None, [self.STEP], AT)
        store.finish_run("run-2", "done", None, [replace(self.STEP, step="later")], AT)

        assert [s.step for s in store.run_steps("run-2")] == ["extract", "later"]
        run = store.get_run("run-2")
        assert run is not None
        assert (run.status, run.tokens_in) == ("done", 200)

    def test_steps_are_numbered_through_the_whole_run(self, store: SqliteStore, path: Path) -> None:
        store.start_run("run-2", "tailor", None, AT)
        store.finish_run("run-2", "waiting", None, [self.STEP, self.STEP], AT)
        store.finish_run("run-2", "done", None, [self.STEP], AT)
        db = sqlite3.connect(path)
        try:
            ordinals = [
                row[0] for row in db.execute("SELECT ordinal FROM run_steps WHERE run_id = 'run-2' ORDER BY id")
            ]
        finally:
            db.close()
        assert ordinals == [1, 2, 3]

    def test_a_failed_run_keeps_its_reason(self, store: SqliteStore) -> None:
        store.start_run("run-3", "intake", None, AT)
        store.finish_run("run-3", "failed", "budget", [], AT)
        run = store.get_run("run-3")
        assert run is not None
        assert (run.status, run.reason) == ("failed", "budget")

    def test_runs_are_listed_newest_first_up_to_a_limit(self, store: SqliteStore) -> None:
        for i in range(5):
            store.start_run(f"run-{i}", "intake", None, AT + timedelta(minutes=i))
        assert [r.id for r in store.list_runs(limit=3)] == ["run-4", "run-3", "run-2"]
        assert store.get_run("nope") is None

    def test_a_run_id_is_used_once(self, store: SqliteStore) -> None:
        store.start_run("run-1", "intake", None, AT)
        with pytest.raises(sqlite3.IntegrityError):
            store.start_run("run-1", "intake", None, AT)


class TestTokens:
    def test_tokens_add_up_per_day(self, store: SqliteStore) -> None:
        today, tomorrow = date(2026, 11, 13), date(2026, 11, 14)
        assert store.tokens_on(today) == 0
        store.add_tokens(today, 1200)
        store.add_tokens(today, 300)
        store.add_tokens(tomorrow, 7)
        assert (store.tokens_on(today), store.tokens_on(tomorrow)) == (1500, 7)


class TestTheFile:
    def test_what_was_saved_is_there_after_closing_and_opening(self, path: Path) -> None:
        first = SqliteStore(path)
        stored, _ = first.add_posting(example_posting(), AT)
        first.save_job(job_record(stored.id))
        first.close()

        second = SqliteStore(path)
        try:
            assert second.get_job(stored.id) == job_record(stored.id)
        finally:
            second.close()

    def test_migrations_are_applied_once(self, path: Path) -> None:
        SqliteStore(path).close()
        SqliteStore(path).close()
        db = sqlite3.connect(path)
        try:
            versions = [row[0] for row in db.execute("SELECT version FROM schema_migrations ORDER BY version")]
            mode = db.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            db.close()
        assert versions == [version for version, _ in migrations()]
        assert versions == sorted(set(versions))
        assert versions[0] == 1
        assert mode == "wal"

    def test_a_migration_that_fails_leaves_no_half_schema(self, path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        broken = [*migrations(), (999, "CREATE TABLE half_done (id INTEGER); CREATE TABLE postings (id INTEGER);")]
        monkeypatch.setattr(sqlite_store, "migrations", lambda: broken)
        with pytest.raises(sqlite3.OperationalError) as error:
            SqliteStore(path)
        monkeypatch.undo()

        # The failed store holds no lock, even while its error is still in hand: another process can write at once.
        other = sqlite3.connect(path, timeout=0)
        try:
            other.execute("BEGIN IMMEDIATE")
            other.execute("ROLLBACK")
        finally:
            other.close()
        assert error.value is not None

        db = sqlite3.connect(path)
        try:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            versions = [row[0] for row in db.execute("SELECT version FROM schema_migrations")]
        finally:
            db.close()
        assert "half_done" not in tables
        assert 999 not in versions
        SqliteStore(path).close()  # and the file still opens

    def test_foreign_keys_are_on(self, store: SqliteStore) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            store.add_document(document(4242))

    def test_a_write_that_fails_is_rolled_back_whole(self, store: SqliteStore) -> None:
        store.start_run("run-1", "intake", None, AT)
        bad = replace(TestRuns.STEP, output=None)  # type: ignore[arg-type]
        with pytest.raises(sqlite3.IntegrityError):
            store.finish_run("run-1", "done", None, [TestRuns.STEP, bad], AT)

        assert store.run_steps("run-1") == []
        run = store.get_run("run-1")
        assert run is not None
        assert run.status == "running"

    def test_the_checkpointer_lives_in_the_same_file(self, store: SqliteStore, path: Path) -> None:
        saver = open_checkpointer(path)
        try:
            tables = {row[0] for row in saver.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        finally:
            saver.conn.close()
        assert {"checkpoints", "postings", "documents"} <= tables
        # And the store still works beside it.
        assert store.add_posting(example_posting(), AT)[1] is True
