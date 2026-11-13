"""Settings come from the environment. The key is never stored and never printed."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

PROVIDERS = ("openai", "anthropic")
DEFAULT_DAILY_TOKENS = 400_000


class SettingsError(Exception):
    """A setting is missing or wrong. The message says which, and never holds a value that is secret."""


@dataclass(frozen=True)
class Settings:
    home: Path
    provider: str | None = None
    model: str | None = None
    api_key: str | None = field(default=None, repr=False)
    base_url: str | None = None
    daily_tokens: int = DEFAULT_DAILY_TOKENS

    @property
    def database(self) -> Path:
        return self.home / "masar.db"

    @property
    def career_file(self) -> Path:
        return self.home / "career.yaml"

    @property
    def watchlist_file(self) -> Path:
        return self.home / "watchlist.yaml"

    @property
    def has_model(self) -> bool:
        return self.provider is not None

    def shown(self) -> dict[str, str | int | None]:
        """The settings as they may be printed."""
        return {
            "home": str(self.home),
            "provider": self.provider,
            "model": self.model,
            "api_key": "***" if self.api_key else None,
            # An address can carry a name and a password before the "@".
            "base_url": re.sub(r"//[^/@]*@", "//***@", self.base_url) if self.base_url else None,
            "daily_tokens": self.daily_tokens,
        }


def load_settings(environ: Mapping[str, str]) -> Settings:
    def get(name: str) -> str | None:
        value = environ.get(name, "").strip()
        return value or None

    home = Path(get("MASAR_HOME") or (Path(environ.get("HOME", "~")).expanduser() / ".masar"))
    provider = get("MASAR_LLM_PROVIDER")
    if provider is not None:
        provider = provider.casefold()
        if provider not in PROVIDERS:
            raise SettingsError(f"MASAR_LLM_PROVIDER must be one of: {', '.join(PROVIDERS)}")
        missing = [name for name in ("MASAR_LLM_MODEL", "MASAR_LLM_API_KEY") if get(name) is None]
        if missing:
            raise SettingsError(f"with MASAR_LLM_PROVIDER set, these are needed too: {', '.join(missing)}")
    raw = get("MASAR_DAILY_TOKENS")
    try:
        daily = int(raw) if raw is not None else DEFAULT_DAILY_TOKENS
    except ValueError:
        raise SettingsError("MASAR_DAILY_TOKENS must be a whole number") from None
    if daily < 0:
        raise SettingsError("MASAR_DAILY_TOKENS must not be negative")
    return Settings(
        home=home,
        provider=provider,
        model=get("MASAR_LLM_MODEL"),
        api_key=get("MASAR_LLM_API_KEY"),
        base_url=get("MASAR_LLM_BASE_URL"),
        daily_tokens=daily,
    )
