"""Results, not exceptions: a rule returns its value and what it found on the way."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing a rule noticed: a stable code for programs, a path to the place, a message for people."""

    code: str
    path: str
    message: str
    severity: Severity = Severity.ERROR

    @staticmethod
    def error(code: str, path: str, message: str) -> Finding:
        return Finding(code, path, message, Severity.ERROR)

    @staticmethod
    def warning(code: str, path: str, message: str) -> Finding:
        return Finding(code, path, message, Severity.WARNING)


@dataclass(frozen=True, slots=True)
class Result[T]:
    """A value, or the reasons there is none. Warnings may come with a value."""

    value: T | None
    findings: tuple[Finding, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.value is not None and not self.errors

    @property
    def errors(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.WARNING)

    def unwrap(self) -> T:
        """The value. For tests and for callers that already checked ``ok``."""
        if self.value is None or self.errors:
            raise ValueError("; ".join(f"{f.code} {f.path}: {f.message}" for f in self.errors) or "no value")
        return self.value
