"""A whole Masar in a temporary folder: a real database, real files, a scripted model, a clock a test moves."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from masar.adapters.checkpoint import open_checkpointer
from masar.adapters.files import LocalFiles
from masar.adapters.scripted import ScriptedModel
from masar.adapters.sqlite_store import SqliteStore
from masar.app.service import Masar
from masar.domain.job import Posting
from masar.ports.sources import Board, FetchResult
from tests.support.career import EXAMPLE
from tests.support.clock import FakeClock
from tests.support.postings import TEXT


class FakeBoards:
    def __init__(self, results: dict[str, FetchResult] | None = None) -> None:
        self.results = results or {}
        self.asked: list[Board] = []

    def fetch(self, board: Board) -> FetchResult:
        self.asked.append(board)
        return self.results.get(board.board, FetchResult(board, error="HTTP 404"))

    def serve(self, board: Board, *postings: Posting, skipped: int = 0) -> None:
        self.results[board.board] = FetchResult(board, tuple(postings), skipped)


@dataclass
class World:
    home: Path
    answers: list[Any] = field(default_factory=list)
    daily_tokens: int = 400_000
    with_model: bool = True

    def __post_init__(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.career_path = self.home / "career.yaml"
        self.watchlist_path = self.home / "watchlist.yaml"
        if not self.career_path.exists():
            self.career_path.write_bytes(EXAMPLE.read_bytes())
        self.clock = FakeClock()
        self.model = ScriptedModel(self.answers)
        self.boards = FakeBoards()
        self.store = SqliteStore(self.home / "masar.db")
        self.checkpointer = open_checkpointer(self.home / "masar.db")
        self._ids = 0
        self._closed = False
        self.app = Masar(
            store=self.store,
            files=LocalFiles(self.career_path, self.watchlist_path),
            clock=self.clock,
            checkpointer=self.checkpointer,
            model=self.model if self.with_model else None,
            boards=self.boards,
            daily_tokens=self.daily_tokens,
            new_id=self._next_id,
        )

    def _next_id(self) -> str:
        self._ids += 1
        return f"run-{self._ids:04d}"

    def script(self, *answers: Any) -> None:
        """Adds answers for the model's next calls."""
        self.model._answers.extend(answers)

    def add(self, company: str = "Tamween", title: str = "Backend Engineer", text: str = TEXT) -> int:
        stored, _ = self.app.add_posting(company, title, text)
        return stored.id

    def edit_career(self, old: str, new: str) -> None:
        content = self.career_path.read_text(encoding="utf-8")
        assert old in content
        self.career_path.write_text(content.replace(old, new), encoding="utf-8")

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self.checkpointer.conn.close()
            self.store.close()

    def restart(self) -> World:
        """The same folder in a new process: new connections, a new model with nothing to say."""
        self.close()
        again = World(self.home, daily_tokens=self.daily_tokens, with_model=self.with_model)
        again.clock = self.clock
        again.app._clock = self.clock
        again._ids = self._ids
        return again
