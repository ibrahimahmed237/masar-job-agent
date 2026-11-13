"""Putting a Masar together from settings."""

from __future__ import annotations

from pathlib import Path

import pytest

from masar.adapters.llm import AnthropicModel
from masar.adapters.settings import Settings
from masar.adapters.wiring import open_masar
from masar.app.errors import NoModel
from tests.support.postings import TEXT


def test_a_folder_that_does_not_exist_yet_is_made_and_gets_its_database(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "new" / "masar")
    opened = open_masar(settings)
    try:
        stored, created = opened.app.add_posting("Tamween", "Backend Engineer", TEXT)
        assert (stored.id, created) == (1, True)
        with pytest.raises(NoModel):
            opened.app.assess(1)  # no model was configured, and none was made up
    finally:
        opened.close()
    assert settings.database.exists()

    again = open_masar(settings)
    try:
        assert again.app.job(1).posting.posting.company == "Tamween"
    finally:
        again.close()


def test_the_configured_model_and_the_real_job_boards_are_used_by_default(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "masar", provider="anthropic", model="claude-x", api_key="sk-test", daily_tokens=77)
    opened = open_masar(settings)
    try:
        assert isinstance(opened.app._model, AnthropicModel)
        assert type(opened.app._boards).__name__ == "HttpJobBoards"
        assert opened.app.tokens_today() == (0, 77)
    finally:
        opened.close()
