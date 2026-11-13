"""Time comes from outside, so that a test can set it."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """The current time, in UTC."""
        ...

    def monotonic(self) -> float:
        """Seconds on a clock that only goes forward, for measuring how long something took."""
        ...
