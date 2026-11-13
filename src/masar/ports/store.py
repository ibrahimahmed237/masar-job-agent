"""What Masar keeps: postings, jobs, documents, applications, runs, and the tokens of each day."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from masar.domain.applications import State
from masar.domain.claims import Block, DocumentKind
from masar.domain.document import DroppedBlock
from masar.domain.findings import Finding
from masar.domain.job import Job, Posting
from masar.domain.matching import Assessment, Flag, Recommendation

NEW = "new"  # a posting that no intake run has read yet


@dataclass(frozen=True, slots=True)
class StoredPosting:
    id: int
    posting: Posting
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class JobRecord:
    """What the intake flow made of a posting."""

    posting_id: int
    status: str  # assessed, screened, unreadable, failed
    job: Job | None
    findings: tuple[Finding, ...]
    flags: tuple[Flag, ...]
    assessment: Assessment | None
    score: int | None
    recommendation: Recommendation | None
    career_checksum: str | None
    assessed_at: datetime


@dataclass(frozen=True, slots=True)
class JobSummary:
    """One line of the job list."""

    posting_id: int
    company: str
    title: str
    location: str | None
    url: str | None
    status: str  # new, or a JobRecord status
    score: int | None
    recommendation: Recommendation | None
    flags: tuple[Flag, ...]
    state: State
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    id: int
    posting_id: int
    kind: DocumentKind
    language: str
    status: str  # pending, approved, rejected, failed
    markdown: str
    blocks: tuple[Block, ...]
    dropped: tuple[DroppedBlock, ...]
    warnings: tuple[str, ...]
    judged: bool
    edited: bool
    reason: str | None
    run_id: str
    career_checksum: str
    created_at: datetime
    decided_at: datetime | None


@dataclass(frozen=True, slots=True)
class ApplicationRecord:
    posting_id: int
    state: State
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ApplicationEvent:
    posting_id: int
    from_state: State | None
    to_state: State
    note: str | None
    at: datetime


@dataclass(frozen=True, slots=True)
class RunStep:
    step: str
    model: str
    prompt_version: str
    tokens_in: int
    tokens_out: int
    duration_ms: int
    input_checksum: str
    output: str


@dataclass(frozen=True, slots=True)
class RunRecord:
    id: str
    kind: str  # intake, tailor
    posting_id: int | None
    status: str  # running, waiting, done, failed
    reason: str | None
    tokens_in: int
    tokens_out: int
    started_at: datetime
    ended_at: datetime | None


class Store(Protocol):
    # Postings
    def add_posting(self, posting: Posting, at: datetime) -> tuple[StoredPosting, bool]:
        """Saves a posting, or returns the one that is already there. The flag says if it is new."""
        ...

    def get_posting(self, posting_id: int) -> StoredPosting | None: ...

    # Jobs
    def save_job(self, record: JobRecord) -> None:
        """Keeps the result of an intake run. A later run for the same posting replaces it."""
        ...

    def get_job(self, posting_id: int) -> JobRecord | None: ...

    def list_jobs(self, status: str | None = None, min_score: int | None = None) -> list[JobSummary]: ...

    # Documents
    def add_document(self, record: DocumentRecord) -> int:
        """Saves a draft and returns its id. The id of the given record is ignored."""
        ...

    def get_document(self, document_id: int) -> DocumentRecord | None: ...

    def list_documents(self, status: str | None = None, posting_id: int | None = None) -> list[DocumentRecord]: ...

    def update_pending_document(self, record: DocumentRecord) -> bool:
        """Writes the record over the stored draft, only while that draft is still pending. False when it is not."""
        ...

    # Applications
    def get_application(self, posting_id: int) -> ApplicationRecord | None: ...

    def list_applications(self) -> list[ApplicationRecord]: ...

    def move_application(self, posting_id: int, expected: State, target: State, note: str | None, at: datetime) -> bool:
        """Moves an application and records the event, only if it is still in the expected state."""
        ...

    def application_events(self, posting_id: int) -> list[ApplicationEvent]: ...

    # Runs
    def start_run(self, run_id: str, kind: str, posting_id: int | None, at: datetime) -> None: ...

    def finish_run(self, run_id: str, status: str, reason: str | None, steps: Sequence[RunStep], at: datetime) -> None:
        """Sets how a run ended and adds its steps to the trace."""
        ...

    def get_run(self, run_id: str) -> RunRecord | None: ...

    def list_runs(self, limit: int = 20) -> list[RunRecord]: ...

    def run_steps(self, run_id: str) -> list[RunStep]: ...

    # Tokens
    def tokens_on(self, day: date) -> int: ...

    def add_tokens(self, day: date, tokens: int) -> None: ...
