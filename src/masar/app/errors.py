"""What a use case says when it does not do what was asked."""

from __future__ import annotations

from masar.domain.findings import Finding


class AppError(Exception):
    """The use case could not run: something is missing or unknown. Hosts report it as "could not run"."""


class NotFound(AppError):
    pass


class NoModel(AppError):
    def __init__(self) -> None:
        super().__init__(
            "this needs a model: set MASAR_LLM_PROVIDER (openai or anthropic), MASAR_LLM_MODEL and MASAR_LLM_API_KEY"
        )


class CareerInvalid(AppError):
    def __init__(self, findings: tuple[Finding, ...]) -> None:
        super().__init__("the career file has errors; run: masar profile check")
        self.findings = findings


class DailyLimit(AppError):
    def __init__(self, used: int, limit: int) -> None:
        super().__init__(f"today's token limit is reached ({used} of {limit}); it starts again tomorrow (UTC)")


class Refused(Exception):
    """The use case ran and the answer is no: a move that is not allowed, a draft that is already decided."""
