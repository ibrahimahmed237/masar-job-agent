"""Where postings come from, besides the person pasting one."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from masar.domain.job import Posting, Source


@dataclass(frozen=True, slots=True)
class Board:
    """One company's job board, as the watchlist names it."""

    source: Source
    board: str
    company: str
    region: str | None = None  # Lever: "eu" for the European service


@dataclass(frozen=True, slots=True)
class FetchResult:
    board: Board
    postings: tuple[Posting, ...] = ()
    skipped: int = 0  # postings with no title or too little text
    error: str | None = None  # why this board could not be read


class JobBoards(Protocol):
    def fetch(self, board: Board) -> FetchResult:
        """The open postings of one board. Never raises: a board that cannot be read gives an error."""
        ...
