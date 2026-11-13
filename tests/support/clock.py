"""A clock that a test moves by hand."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class FakeClock:
    def __init__(self, start: datetime = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)) -> None:
        self._now = start
        self._ticks = 0.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._ticks

    def advance(self, seconds: float) -> None:
        self._ticks += seconds
        self._now += timedelta(seconds=seconds)
