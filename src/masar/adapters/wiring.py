"""Puts a Masar together from its settings: the one place where ports meet their adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from masar.adapters.boards import HttpJobBoards
from masar.adapters.checkpoint import open_checkpointer
from masar.adapters.clock import SystemClock
from masar.adapters.files import LocalFiles
from masar.adapters.llm import build_model
from masar.adapters.settings import Settings
from masar.adapters.sqlite_store import SqliteStore
from masar.app.service import Masar
from masar.ports.clock import Clock
from masar.ports.model import ChatModel
from masar.ports.sources import JobBoards


@dataclass
class Opened:
    app: Masar
    close: Callable[[], None]


def open_masar(
    settings: Settings,
    *,
    model: ChatModel | None = None,
    boards: JobBoards | None = None,
    clock: Clock | None = None,
    new_id: Callable[[], str] | None = None,
) -> Opened:
    """Opens the database of the Masar folder and builds the use cases on it. Call ``close`` when done.

    A model, job boards, a clock or a maker of run ids given here take the place of the real ones: for tests
    and the demo.
    """
    settings.home.mkdir(parents=True, exist_ok=True)
    store = SqliteStore(settings.database)
    checkpointer = open_checkpointer(settings.database)
    http_boards = HttpJobBoards() if boards is None else None
    if model is None and settings.has_model:
        model = build_model(settings)

    def close() -> None:
        if http_boards is not None:
            http_boards.close()
        checkpointer.conn.close()
        store.close()

    ids = {"new_id": new_id} if new_id is not None else {}
    app = Masar(
        store=store,
        files=LocalFiles(settings.career_file, settings.watchlist_file),
        clock=clock or SystemClock(),
        checkpointer=checkpointer,
        model=model,
        boards=boards or http_boards,
        daily_tokens=settings.daily_tokens,
        **ids,
    )
    return Opened(app, close)
