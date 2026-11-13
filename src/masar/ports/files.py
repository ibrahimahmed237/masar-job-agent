"""The files the person keeps, as the use cases see them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from masar.domain.career import Career
from masar.domain.findings import Result
from masar.ports.sources import Board


class FileProblem(Exception):
    """A file that cannot be read or written as what it should be. The message is for the person."""


@dataclass(frozen=True)
class CareerFile:
    """The career file as read: the career or its faults, and a checksum of the file's bytes."""

    result: Result[Career]
    checksum: str


class Files(Protocol):
    def career(self) -> CareerFile:
        """Reads the career file now. Raises ``FileProblem`` when there is no file, or it is not YAML."""
        ...

    def watchlist(self) -> Result[tuple[Board, ...]]:
        """Reads the watchlist now. Raises ``FileProblem``."""
        ...
