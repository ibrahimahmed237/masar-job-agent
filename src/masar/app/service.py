"""The use cases. Hosts call these; these call the domain, the flows and the ports. No rule lives in a host."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from masar.agent.intake import IntakeDeps, run_intake
from masar.agent.prompts import PROMPT_VERSION
from masar.agent.session import Budget, BudgetExceeded, ModelOutputError, ModelSession, NoModel
from masar.agent.tailor import (
    APPROVED,
    FAILED,
    PENDING,
    REJECTED,
    NotPaused,
    TailorDeps,
    TailorOutcome,
    build_tailor_graph,
    resume_tailor,
    snapshot,
    start_tailor,
)
from masar.app import errors
from masar.domain.applications import Actor, ApplicationView, Attention, State, move, needs_attention
from masar.domain.career import Career, Fact
from masar.domain.claims import Block, BlockKind, ClaimContext, DocumentKind, Section, Violation, check_block
from masar.domain.findings import Finding
from masar.domain.job import Posting, Source
from masar.domain.matching import title_matches
from masar.domain.text import without_unseen
from masar.ports.clock import Clock
from masar.ports.files import FileProblem, Files
from masar.ports.model import ChatModel, ModelUnavailable
from masar.ports.sources import Board, JobBoards
from masar.ports.store import (
    NEW,
    ApplicationEvent,
    ApplicationRecord,
    DocumentRecord,
    JobRecord,
    JobSummary,
    RunRecord,
    RunStep,
    Store,
    StoredPosting,
)

MAX_POSTING_TEXT = 200_000
LANGUAGES = ("en", "ar")
UNAVAILABLE = "model unavailable"


@dataclass(frozen=True)
class ProfileReport:
    errors: tuple[Finding, ...]
    warnings: tuple[Finding, ...]
    years: float | None
    skills: tuple[str, ...]
    facts: int
    checksum: str

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class FetchReport:
    board: Board
    new: int = 0
    known: int = 0
    filtered: int = 0  # the title did not pass the person's filter
    skipped: int = 0  # the board gave a posting with no title or too little text
    error: str | None = None


@dataclass(frozen=True)
class JobDetail:
    posting: StoredPosting
    job: JobRecord | None
    application: ApplicationRecord
    stale: bool  # assessed with a career file that has changed since


@dataclass(frozen=True)
class AssessResult:
    posting_id: int
    run_id: str
    record: JobRecord
    reason: str | None  # why the run failed


@dataclass(frozen=True)
class DraftResult:
    document: DocumentRecord
    problem: str | None = None  # why the last decision was not taken
    moved_to_drafted: bool = False


@dataclass(frozen=True)
class TodayItem:
    posting_id: int
    company: str
    title: str
    reason: Attention
    days: int


@dataclass(frozen=True)
class FactView:
    id: str
    kind: str
    text: str
    skills: tuple[str, ...]
    org: str | None
    role: str | None
    period: str | None


class Masar:
    def __init__(
        self,
        *,
        store: Store,
        files: Files,
        clock: Clock,
        checkpointer: Any,
        model: ChatModel | None = None,
        boards: JobBoards | None = None,
        daily_tokens: int = 400_000,
        new_id: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self._store = store
        self._files = files
        self._clock = clock
        self._checkpointer = checkpointer
        self._model = model
        self._boards = boards
        self._daily_tokens = daily_tokens
        self._new_id = new_id

    # The career file

    def _today(self) -> date:
        return self._clock.now().date()

    def _career(self) -> tuple[Career, str]:
        loaded = self._files.career()
        if loaded.result.value is None:
            raise errors.CareerInvalid(loaded.result.errors)
        return loaded.result.value, loaded.checksum

    def profile(self) -> ProfileReport:
        loaded = self._files.career()
        career = loaded.result.value
        return ProfileReport(
            errors=loaded.result.errors,
            warnings=loaded.result.warnings,
            years=round(career.years_of_experience(self._today()), 1) if career else None,
            skills=tuple(sorted(career.skill_spellings, key=str.casefold)) if career else (),
            facts=len(career.facts) if career else 0,
            checksum=loaded.checksum,
        )

    def list_facts(self) -> list[FactView]:
        """The facts, without the person: no name, no contacts, no limits."""
        career, _ = self._career()
        return [_fact_view(fact) for fact in career.facts]

    # Postings

    def add_posting(
        self, company: str, title: str, text: str, url: str | None = None, location: str | None = None
    ) -> tuple[StoredPosting, bool]:
        if url and url.strip() and not _is_web_address(url.strip()):
            raise errors.AppError("the address of a posting starts with http:// or https://")
        posting = _admitted(Posting(Source.MANUAL, company, title, text, url, location))
        if not posting.company or not posting.title:
            raise errors.AppError("a posting needs a company and a title")
        if not posting.text:
            raise errors.AppError("the posting has no text")
        if len(posting.text) > MAX_POSTING_TEXT:
            raise errors.AppError(f"the posting is longer than {MAX_POSTING_TEXT} characters")
        return self._store.add_posting(posting, self._clock.now())

    def fetch(self) -> list[FetchReport]:
        """Reads every board of the watchlist and keeps the new postings whose title passes the person's filter."""
        if self._boards is None:
            raise errors.AppError("no job boards are configured")
        career, _ = self._career()
        watchlist = self._files.watchlist()
        if watchlist.value is None:
            problems = "; ".join(f"{f.path}: {f.message}" for f in watchlist.errors)
            raise errors.AppError(f"the watchlist has errors: {problems}")
        reports = []
        for board in watchlist.value:
            result = self._boards.fetch(board)
            new = known = filtered = 0
            skipped = result.skipped
            for posting in map(_admitted, result.postings):
                if not posting.title or not posting.text or len(posting.text) > MAX_POSTING_TEXT:
                    skipped += 1  # nothing left after cleaning, or far too long to be a posting
                    continue
                if not title_matches(posting.title, career.limits):
                    filtered += 1
                    continue
                _, created = self._store.add_posting(posting, self._clock.now())
                new += created
                known += not created
            reports.append(FetchReport(board, new, known, filtered, skipped, result.error))
        return reports

    def _posting(self, posting_id: int) -> StoredPosting:
        stored = self._store.get_posting(posting_id)
        if stored is None:
            raise errors.NotFound(f"there is no job {posting_id}")
        return stored

    # Jobs

    def list_jobs(self, status: str | None = None, min_score: int | None = None) -> list[JobSummary]:
        return self._store.list_jobs(status, min_score)

    def job(self, posting_id: int) -> JobDetail:
        stored = self._posting(posting_id)
        record = self._store.get_job(posting_id)
        application = self._store.get_application(posting_id)
        assert application is not None  # every posting has one from the start
        stale = False
        if record is not None and record.career_checksum is not None:
            try:
                stale = self._files.career().checksum != record.career_checksum
            except FileProblem:
                stale = False  # a missing career file is reported where it matters, not here
        return JobDetail(stored, record, application, stale)

    # Model runs

    def _session(self) -> ModelSession:
        """A session for one run, within what is left of today's tokens."""
        if self._model is None:
            raise errors.NoModel
        used = self._store.tokens_on(self._today())
        if used >= self._daily_tokens:
            raise errors.DailyLimit(used, self._daily_tokens)
        budget = Budget()
        budget = replace(budget, tokens=min(budget.tokens, self._daily_tokens - used))
        return ModelSession(self._model, self._clock, PROMPT_VERSION, budget)

    def _close_run(self, run_id: str, status: str, reason: str | None, session: ModelSession) -> None:
        steps = [
            RunStep(
                s.step, s.model, s.prompt_version, s.tokens_in, s.tokens_out, s.duration_ms, s.input_checksum, s.output
            )
            for s in session.steps
        ]
        self._store.finish_run(run_id, status, reason, steps, self._clock.now())
        if session.tokens:
            self._store.add_tokens(self._today(), session.tokens)

    def assess(self, posting_id: int) -> AssessResult:
        """Runs the intake flow on one posting and keeps the result, also when the run fails."""
        stored = self._posting(posting_id)
        session = self._session()
        career, checksum = self._career()
        run_id = self._new_id()
        self._store.start_run(run_id, "intake", posting_id, self._clock.now())
        reason: str | None = None
        try:
            result = run_intake(IntakeDeps(session, career, self._today()), stored.posting)
        except (BudgetExceeded, ModelOutputError, ModelUnavailable) as error:
            reason = _reason(error)
            record = JobRecord(posting_id, "failed", None, (), (), None, None, None, checksum, self._clock.now())
        else:
            record = JobRecord(
                posting_id=posting_id,
                status=result.status,
                job=result.job,
                findings=result.findings,
                flags=result.flags,
                assessment=result.assessment,
                score=result.score,
                recommendation=result.recommendation,
                career_checksum=checksum,
                assessed_at=self._clock.now(),
            )
        self._store.save_job(record)
        self._close_run(run_id, "failed" if reason else "done", reason, session)
        return AssessResult(posting_id, run_id, record, reason)

    def assess_new(self) -> list[AssessResult]:
        """Assesses every posting that has not been read yet. Stops at the first run that the provider or the
        day's limit ends: the next ones would end the same way."""
        results: list[AssessResult] = []
        for summary in reversed(self._store.list_jobs(status=NEW)):
            try:
                result = self.assess(summary.posting_id)
            except errors.DailyLimit:
                if not results:
                    raise
                break
            results.append(result)
            if result.reason and result.reason.startswith(UNAVAILABLE):
                break
        return results

    def _graph(self, session: ModelSession, career: Career) -> Any:
        return build_tailor_graph(TailorDeps(session, career, self._today()), self._checkpointer)

    def draft(self, posting_id: int, kind: DocumentKind, language: str = "en") -> DraftResult:
        """Runs the tailor flow until it waits for the person, and keeps the draft."""
        if language not in LANGUAGES:
            raise errors.AppError(f"language must be one of: {', '.join(LANGUAGES)}")
        stored = self._posting(posting_id)
        record = self._store.get_job(posting_id)
        if record is None or record.job is None:
            raise errors.AppError(f"job {posting_id} has not been read yet; run: masar assess {posting_id}")
        session = self._session()
        career, checksum = self._career()
        run_id = self._new_id()
        now = self._clock.now()
        self._store.start_run(run_id, "tailor", posting_id, now)
        document = DocumentRecord(
            id=0,
            posting_id=posting_id,
            kind=kind,
            language=language,
            status=FAILED,
            markdown="",
            blocks=(),
            dropped=(),
            warnings=(),
            judged=False,
            edited=False,
            reason=None,
            run_id=run_id,
            career_checksum=checksum,
            created_at=now,
            decided_at=None,
        )
        try:
            outcome = start_tailor(
                self._graph(session, career),
                run_id,
                kind=kind,
                language=language,
                job=record.job,
                assessment=record.assessment,
                posting_text=stored.posting.text,
            )
        except (BudgetExceeded, ModelOutputError, ModelUnavailable) as error:
            document = replace(document, reason=_reason(error))
        else:
            document = _with_outcome(document, outcome)
        document = replace(document, id=self._store.add_document(document))
        waiting = document.status == PENDING
        self._close_run(run_id, "waiting" if waiting else "failed", document.reason, session)
        return DraftResult(document)

    # Drafts

    def list_drafts(self, status: str | None = None) -> list[DocumentRecord]:
        return self._store.list_documents(status)

    def get_draft(self, document_id: int) -> DocumentRecord:
        document = self._store.get_document(document_id)
        if document is None:
            raise errors.NotFound(f"there is no draft {document_id}")
        return document

    def decide(self, document_id: int, action: str, blocks: Any = None) -> DraftResult:
        """The person's decision on a waiting draft: approve, reject, or edit with new blocks.

        This is the only way a document becomes approved, and no model is asked on the way.
        """
        document = self.get_draft(document_id)
        if document.status != PENDING:
            raise errors.Refused(f"draft {document_id} is {document.status}; only a waiting draft can be decided")
        career, _ = self._career()
        graph = self._graph(ModelSession(NoModel(), self._clock, PROMPT_VERSION), career)
        decision: Mapping[str, Any] = {"action": action, "blocks": blocks}
        try:
            outcome = resume_tailor(graph, document.run_id, decision)
        except NotPaused:
            # The flow was decided, and the process stopped before the draft was updated. Take the flow's word.
            found = snapshot(graph, document.run_id)
            if found is None or found.status not in (APPROVED, REJECTED):
                raise errors.AppError(f"the run of draft {document_id} cannot be continued; draft it again") from None
            outcome = found
        updated = _with_outcome(document, outcome)
        decided = updated.status in (APPROVED, REJECTED)
        if decided:
            updated = replace(updated, decided_at=self._clock.now())
        if updated != document and not self._store.update_pending_document(updated):
            raise errors.Refused(f"draft {document_id} was decided in the meantime")
        moved = False
        if decided:
            self._store.finish_run(document.run_id, "done", None, [], self._clock.now())
        if updated.status == APPROVED:
            moved = self._mark_drafted(document.posting_id)
        return DraftResult(updated, outcome.problem, moved)

    def _mark_drafted(self, posting_id: int) -> bool:
        application = self._store.get_application(posting_id)
        if application is None or move(application.state, State.DRAFTED, Actor.MASAR).value is None:
            return False
        note = "a document was approved"
        return self._store.move_application(posting_id, application.state, State.DRAFTED, note, self._clock.now())

    def approved_document(self, document_id: int) -> tuple[DocumentRecord, StoredPosting]:
        """A document that may leave Masar: only an approved one."""
        document = self.get_draft(document_id)
        if document.status != APPROVED:
            raise errors.Refused(f"draft {document_id} is {document.status}; only an approved document is exported")
        return document, self._posting(document.posting_id)

    # Applications

    def applications(self) -> list[tuple[ApplicationRecord, StoredPosting]]:
        return [(a, self._posting(a.posting_id)) for a in self._store.list_applications()]

    def move_application(self, posting_id: int, target: str, note: str | None = None) -> ApplicationRecord:
        self._posting(posting_id)
        application = self._store.get_application(posting_id)
        assert application is not None
        try:
            wanted = State(target.strip().casefold())
        except ValueError:
            raise errors.AppError(f"'{target}' is not a state; states: {', '.join(s.value for s in State)}") from None
        allowed = move(application.state, wanted, Actor.PERSON)
        if allowed.value is None:
            raise errors.Refused(allowed.errors[0].message)
        note = " ".join(note.split())[:500] if note and note.strip() else None
        if not self._store.move_application(posting_id, application.state, wanted, note, self._clock.now()):
            raise errors.Refused(f"job {posting_id} was moved in the meantime; look again")
        moved = self._store.get_application(posting_id)
        assert moved is not None
        return moved

    def history(self, posting_id: int) -> list[ApplicationEvent]:
        self._posting(posting_id)
        return self._store.application_events(posting_id)

    def today(self) -> list[TodayItem]:
        """What the person should look at today."""
        documents = self._store.list_documents()
        views = []
        for application in self._store.list_applications():
            mine = [d for d in documents if d.posting_id == application.posting_id]
            views.append(
                ApplicationView(
                    posting_id=application.posting_id,
                    state=application.state,
                    last_event=application.updated_at.date(),
                    pending_drafts=sum(d.status == PENDING for d in mine),
                    approved_documents=sum(d.status == APPROVED for d in mine),
                )
            )
        items = []
        for item in needs_attention(views, self._today()):
            posting = self._posting(item.posting_id).posting
            items.append(TodayItem(item.posting_id, posting.company, posting.title, item.reason, item.days))
        return items

    # Runs

    def runs(self, limit: int = 20) -> list[RunRecord]:
        return self._store.list_runs(limit)

    def run(self, run_id: str) -> tuple[RunRecord, list[RunStep]]:
        record = self._store.get_run(run_id)
        if record is None:
            matches = [r for r in self._store.list_runs(200) if r.id.startswith(run_id)] if len(run_id) >= 6 else []
            if len(matches) != 1:
                raise errors.NotFound(f"there is no run {run_id}")
            record = matches[0]
        return record, self._store.run_steps(record.id)

    def tokens_today(self) -> tuple[int, int]:
        return self._store.tokens_on(self._today()), self._daily_tokens

    # Checking a text someone else wrote

    def check_claims(
        self, text: str, fact_ids: list[str], *, language: str = "en", posting_id: int | None = None
    ) -> list[Violation]:
        """The claim checks on one sentence or paragraph that rests on the given facts."""
        if language not in LANGUAGES:
            raise errors.AppError(f"language must be one of: {', '.join(LANGUAGES)}")
        career, _ = self._career()
        job = None
        posting_text = ""
        if posting_id is not None:
            stored = self._posting(posting_id)
            record = self._store.get_job(posting_id)
            job = record.job if record else None
            posting_text = stored.posting.text
        context = ClaimContext(career, self._today(), language, job, posting_text)
        block = Block(Section.BODY, BlockKind.CLAIM, " ".join(text.split()), tuple(dict.fromkeys(fact_ids)))
        return check_block(block, 0, context)


def _is_web_address(url: str) -> bool:
    return url.casefold().startswith(("http://", "https://")) and " " not in url


def _admitted(posting: Posting) -> Posting:
    """A posting as it is let in: text from outside, with nothing in it that draws nothing.

    A posting is shown in a terminal and given to assistants. Control characters could recolour or hide what
    the person reads there, so they go at the door, for pasted postings and fetched ones alike.
    """

    def line(value: str | None) -> str:
        return " ".join(without_unseen(value or "").split())

    url = line(posting.url)
    return replace(
        posting,
        company=line(posting.company),
        title=line(posting.title),
        text=without_unseen(posting.text).strip(),
        url=url if _is_web_address(url) else None,
        location=line(posting.location) or None,
    )


def _reason(error: Exception) -> str:
    if isinstance(error, BudgetExceeded):
        return f"budget: {error}"
    if isinstance(error, ModelOutputError):
        return f"model output: {error}"
    return f"{UNAVAILABLE}: {error}"


def _with_outcome(document: DocumentRecord, outcome: TailorOutcome) -> DocumentRecord:
    written = outcome.document
    return replace(
        document,
        status=outcome.status,
        markdown=written.markdown if written else document.markdown,
        blocks=written.blocks if written else document.blocks,
        dropped=written.dropped if written else document.dropped,
        warnings=outcome.warnings,
        judged=outcome.judged,
        edited=outcome.edited,
        reason=outcome.reason,
    )


def _fact_view(fact: Fact) -> FactView:
    return FactView(
        id=fact.id,
        kind=fact.kind.value,
        text=fact.text,
        skills=fact.skills,
        org=fact.org,
        role=fact.role,
        period=str(fact.period) if fact.period else None,
    )
