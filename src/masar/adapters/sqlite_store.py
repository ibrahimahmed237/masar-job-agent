"""The store on one SQLite file (ADR-0006). Plain SQL, numbered migrations, one lock for all threads."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime
from importlib import resources
from pathlib import Path
from typing import Any

from masar.domain import codec
from masar.domain.applications import State
from masar.domain.claims import DocumentKind
from masar.domain.document import DroppedBlock
from masar.domain.job import Posting, Source
from masar.domain.matching import Recommendation
from masar.ports.store import (
    NEW,
    ApplicationEvent,
    ApplicationRecord,
    DocumentRecord,
    JobRecord,
    JobSummary,
    RunRecord,
    RunStep,
    StoredPosting,
)

LOCK_WAIT_SECONDS = 5.0
_MIGRATION = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds")


def _when(value: str) -> datetime:
    return datetime.fromisoformat(value)


def migrations() -> list[tuple[int, str]]:
    """The migration scripts of the package, in order."""
    found = []
    for entry in resources.files("masar.adapters.migrations").iterdir():
        match = _MIGRATION.match(entry.name)
        if match:
            found.append((int(match.group(1)), entry.read_text(encoding="utf-8")))
    return sorted(found)


class SqliteStore:
    def __init__(self, path: Path | str) -> None:
        # One connection for every thread of the process, behind a lock: the MCP server answers from worker threads.
        self._db = sqlite3.connect(path, timeout=LOCK_WAIT_SECONDS, isolation_level=None, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute("PRAGMA foreign_keys = ON")
        try:
            self._migrate()
        except BaseException:
            # Closing ends the open transaction: a migration that failed leaves nothing behind, and no lock.
            self._db.close()
            raise

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _migrate(self) -> None:
        with self._lock:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            done = {row["version"] for row in self._db.execute("SELECT version FROM schema_migrations")}
            for version, script in migrations():
                if version in done:
                    continue
                now = _time(datetime.now(UTC))
                # A script and its record are one transaction: a migration is applied whole, once.
                self._db.executescript(
                    f"BEGIN IMMEDIATE;\n{script}\n"
                    f"INSERT INTO schema_migrations (version, applied_at) VALUES ({version}, '{now}');\nCOMMIT;"
                )

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")

    def _all(self, sql: str, *args: Any) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._db.execute(sql, args))

    def _one(self, sql: str, *args: Any) -> sqlite3.Row | None:
        with self._lock:
            row: sqlite3.Row | None = self._db.execute(sql, args).fetchone()
            return row

    # Postings

    @staticmethod
    def _posting(row: sqlite3.Row) -> StoredPosting:
        posting = Posting(
            source=Source(row["source"]),
            company=row["company"],
            title=row["title"],
            text=row["text"],
            url=row["url"],
            location=row["location"],
            external_id=row["external_id"],
        )
        return StoredPosting(row["id"], posting, _when(row["fetched_at"]))

    def add_posting(self, posting: Posting, at: datetime) -> tuple[StoredPosting, bool]:
        with self._write() as db:
            existing = db.execute(
                "SELECT * FROM postings WHERE checksum = ?"
                " OR (source = ? AND external_id IS NOT NULL AND external_id = ?)",
                (posting.checksum, posting.source.value, posting.external_id),
            ).fetchone()
            if existing is not None:
                return self._posting(existing), False
            cursor = db.execute(
                "INSERT INTO postings (source, external_id, company, title, url, location, text, checksum, fetched_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    posting.source.value,
                    posting.external_id,
                    posting.company,
                    posting.title,
                    posting.url,
                    posting.location,
                    posting.text,
                    posting.checksum,
                    _time(at),
                ),
            )
            posting_id = cursor.lastrowid
            assert posting_id is not None
            # Every posting has an application from the start, in the first state.
            db.execute(
                "INSERT INTO applications (posting_id, state, updated_at) VALUES (?, ?, ?)",
                (posting_id, State.FOUND.value, _time(at)),
            )
            db.execute(
                "INSERT INTO application_events (posting_id, from_state, to_state, note, at)"
                " VALUES (?, NULL, ?, NULL, ?)",
                (posting_id, State.FOUND.value, _time(at)),
            )
            return StoredPosting(posting_id, posting, _when(_time(at))), True

    def get_posting(self, posting_id: int) -> StoredPosting | None:
        row = self._one("SELECT * FROM postings WHERE id = ?", posting_id)
        return self._posting(row) if row else None

    # Jobs

    def save_job(self, record: JobRecord) -> None:
        with self._write() as db:
            db.execute(
                "INSERT INTO jobs (posting_id, status, job, findings, flags, assessment, score, recommendation,"
                " career_checksum, assessed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (posting_id) DO UPDATE SET status = excluded.status, job = excluded.job,"
                " findings = excluded.findings, flags = excluded.flags, assessment = excluded.assessment,"
                " score = excluded.score, recommendation = excluded.recommendation,"
                " career_checksum = excluded.career_checksum, assessed_at = excluded.assessed_at",
                (
                    record.posting_id,
                    record.status,
                    _dump(codec.job_to_data(record.job)) if record.job else None,
                    _dump(codec.findings_to_data(record.findings)),
                    _dump(codec.flags_to_data(record.flags)),
                    _dump(codec.assessment_to_data(record.assessment)) if record.assessment else None,
                    record.score,
                    record.recommendation.value if record.recommendation else None,
                    record.career_checksum,
                    _time(record.assessed_at),
                ),
            )

    def get_job(self, posting_id: int) -> JobRecord | None:
        row = self._one("SELECT * FROM jobs WHERE posting_id = ?", posting_id)
        if row is None:
            return None
        return JobRecord(
            posting_id=row["posting_id"],
            status=row["status"],
            job=codec.job_from_data(json.loads(row["job"])) if row["job"] else None,
            findings=codec.findings_from_data(json.loads(row["findings"])),
            flags=codec.flags_from_data(json.loads(row["flags"])),
            assessment=codec.assessment_from_data(json.loads(row["assessment"])) if row["assessment"] else None,
            score=row["score"],
            recommendation=Recommendation(row["recommendation"]) if row["recommendation"] else None,
            career_checksum=row["career_checksum"],
            assessed_at=_when(row["assessed_at"]),
        )

    def list_jobs(self, status: str | None = None, min_score: int | None = None) -> list[JobSummary]:
        rows = self._all(
            "SELECT p.id, p.company, p.title, p.location, p.url, p.fetched_at, a.state,"
            " COALESCE(j.status, ?3) AS status, j.score, j.recommendation, j.flags"
            " FROM postings p JOIN applications a ON a.posting_id = p.id LEFT JOIN jobs j ON j.posting_id = p.id"
            " WHERE (?1 IS NULL OR COALESCE(j.status, ?3) = ?1) AND (?2 IS NULL OR j.score >= ?2)"
            # Best first; jobs with no score come after those with one (NULL sorts last here); then the newest.
            " ORDER BY j.score DESC, p.id DESC",
            status,
            min_score,
            NEW,
        )
        return [
            JobSummary(
                posting_id=row["id"],
                company=row["company"],
                title=row["title"],
                location=row["location"],
                url=row["url"],
                status=row["status"],
                score=row["score"],
                recommendation=Recommendation(row["recommendation"]) if row["recommendation"] else None,
                flags=codec.flags_from_data(json.loads(row["flags"])) if row["flags"] else (),
                state=State(row["state"]),
                fetched_at=_when(row["fetched_at"]),
            )
            for row in rows
        ]

    # Documents

    @staticmethod
    def _document(row: sqlite3.Row) -> DocumentRecord:
        return DocumentRecord(
            id=row["id"],
            posting_id=row["posting_id"],
            kind=DocumentKind(row["kind"]),
            language=row["language"],
            status=row["status"],
            markdown=row["markdown"],
            blocks=codec.blocks_from_data(json.loads(row["blocks"])),
            dropped=tuple(DroppedBlock(d["text"], tuple(d["reasons"])) for d in json.loads(row["dropped"])),
            warnings=tuple(json.loads(row["warnings"])),
            judged=bool(row["judged"]),
            edited=bool(row["edited"]),
            reason=row["reason"],
            run_id=row["run_id"],
            career_checksum=row["career_checksum"],
            created_at=_when(row["created_at"]),
            decided_at=_when(row["decided_at"]) if row["decided_at"] else None,
        )

    @staticmethod
    def _document_values(record: DocumentRecord) -> tuple[Any, ...]:
        return (
            record.status,
            record.markdown,
            _dump(codec.blocks_to_data(record.blocks)),
            _dump([{"text": d.text, "reasons": list(d.reasons)} for d in record.dropped]),
            _dump(list(record.warnings)),
            int(record.judged),
            int(record.edited),
            record.reason,
            _time(record.decided_at) if record.decided_at else None,
        )

    def add_document(self, record: DocumentRecord) -> int:
        with self._write() as db:
            cursor = db.execute(
                "INSERT INTO documents (status, markdown, blocks, dropped, warnings, judged, edited, reason,"
                " decided_at, posting_id, kind, language, run_id, career_checksum, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    *self._document_values(record),
                    record.posting_id,
                    record.kind.value,
                    record.language,
                    record.run_id,
                    record.career_checksum,
                    _time(record.created_at),
                ),
            )
            assert cursor.lastrowid is not None
            return cursor.lastrowid

    def get_document(self, document_id: int) -> DocumentRecord | None:
        row = self._one("SELECT * FROM documents WHERE id = ?", document_id)
        return self._document(row) if row else None

    def list_documents(self, status: str | None = None, posting_id: int | None = None) -> list[DocumentRecord]:
        rows = self._all(
            "SELECT * FROM documents WHERE (?1 IS NULL OR status = ?1) AND (?2 IS NULL OR posting_id = ?2)"
            " ORDER BY id DESC",
            status,
            posting_id,
        )
        return [self._document(row) for row in rows]

    def update_pending_document(self, record: DocumentRecord) -> bool:
        with self._write() as db:
            cursor = db.execute(
                "UPDATE documents SET status = ?, markdown = ?, blocks = ?, dropped = ?, warnings = ?, judged = ?,"
                " edited = ?, reason = ?, decided_at = ? WHERE id = ? AND status = 'pending'",
                (*self._document_values(record), record.id),
            )
            return cursor.rowcount == 1

    # Applications

    def get_application(self, posting_id: int) -> ApplicationRecord | None:
        row = self._one("SELECT * FROM applications WHERE posting_id = ?", posting_id)
        return ApplicationRecord(row["posting_id"], State(row["state"]), _when(row["updated_at"])) if row else None

    def list_applications(self) -> list[ApplicationRecord]:
        rows = self._all("SELECT * FROM applications ORDER BY updated_at DESC, posting_id DESC")
        return [ApplicationRecord(row["posting_id"], State(row["state"]), _when(row["updated_at"])) for row in rows]

    def move_application(self, posting_id: int, expected: State, target: State, note: str | None, at: datetime) -> bool:
        with self._write() as db:
            cursor = db.execute(
                "UPDATE applications SET state = ?, updated_at = ? WHERE posting_id = ? AND state = ?",
                (target.value, _time(at), posting_id, expected.value),
            )
            if cursor.rowcount != 1:
                return False
            db.execute(
                "INSERT INTO application_events (posting_id, from_state, to_state, note, at) VALUES (?, ?, ?, ?, ?)",
                (posting_id, expected.value, target.value, note, _time(at)),
            )
            return True

    def application_events(self, posting_id: int) -> list[ApplicationEvent]:
        rows = self._all("SELECT * FROM application_events WHERE posting_id = ? ORDER BY id", posting_id)
        return [
            ApplicationEvent(
                posting_id=row["posting_id"],
                from_state=State(row["from_state"]) if row["from_state"] else None,
                to_state=State(row["to_state"]),
                note=row["note"],
                at=_when(row["at"]),
            )
            for row in rows
        ]

    # Runs

    def start_run(self, run_id: str, kind: str, posting_id: int | None, at: datetime) -> None:
        with self._write() as db:
            db.execute(
                "INSERT INTO runs (id, kind, posting_id, status, started_at) VALUES (?, ?, ?, 'running', ?)",
                (run_id, kind, posting_id, _time(at)),
            )

    def finish_run(self, run_id: str, status: str, reason: str | None, steps: Sequence[RunStep], at: datetime) -> None:
        with self._write() as db:
            first = db.execute(
                "SELECT COALESCE(MAX(ordinal), 0) AS last FROM run_steps WHERE run_id = ?", (run_id,)
            ).fetchone()["last"]
            for offset, step in enumerate(steps, start=1):
                db.execute(
                    "INSERT INTO run_steps (run_id, ordinal, step, model, prompt_version, tokens_in, tokens_out,"
                    " duration_ms, input_checksum, output) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        first + offset,
                        step.step,
                        step.model,
                        step.prompt_version,
                        step.tokens_in,
                        step.tokens_out,
                        step.duration_ms,
                        step.input_checksum,
                        step.output,
                    ),
                )
            db.execute(
                "UPDATE runs SET status = ?, reason = ?, ended_at = ?, tokens_in = tokens_in + ?,"
                " tokens_out = tokens_out + ? WHERE id = ?",
                (
                    status,
                    reason,
                    _time(at),
                    sum(step.tokens_in for step in steps),
                    sum(step.tokens_out for step in steps),
                    run_id,
                ),
            )

    @staticmethod
    def _run(row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            id=row["id"],
            kind=row["kind"],
            posting_id=row["posting_id"],
            status=row["status"],
            reason=row["reason"],
            tokens_in=row["tokens_in"],
            tokens_out=row["tokens_out"],
            started_at=_when(row["started_at"]),
            ended_at=_when(row["ended_at"]) if row["ended_at"] else None,
        )

    def get_run(self, run_id: str) -> RunRecord | None:
        row = self._one("SELECT * FROM runs WHERE id = ?", run_id)
        return self._run(row) if row else None

    def list_runs(self, limit: int = 20) -> list[RunRecord]:
        return [
            self._run(row)
            for row in self._all("SELECT * FROM runs ORDER BY started_at DESC, rowid DESC LIMIT ?", limit)
        ]

    def run_steps(self, run_id: str) -> list[RunStep]:
        rows = self._all("SELECT * FROM run_steps WHERE run_id = ? ORDER BY ordinal", run_id)
        return [
            RunStep(
                step=row["step"],
                model=row["model"],
                prompt_version=row["prompt_version"],
                tokens_in=row["tokens_in"],
                tokens_out=row["tokens_out"],
                duration_ms=row["duration_ms"],
                input_checksum=row["input_checksum"],
                output=row["output"],
            )
            for row in rows
        ]

    # Tokens

    def tokens_on(self, day: date) -> int:
        row = self._one("SELECT tokens FROM usage_daily WHERE day = ?", day.isoformat())
        return int(row["tokens"]) if row else 0

    def add_tokens(self, day: date, tokens: int) -> None:
        with self._write() as db:
            db.execute(
                "INSERT INTO usage_daily (day, tokens) VALUES (?, ?)"
                " ON CONFLICT (day) DO UPDATE SET tokens = tokens + excluded.tokens",
                (day.isoformat(), tokens),
            )
