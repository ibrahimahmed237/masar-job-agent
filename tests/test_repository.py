"""Things that must hold for the repository as a whole."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from masar.domain.text import has_unseen

ROOT = Path(__file__).resolve().parents[1]
TEXT_FILES = {".py", ".md", ".json", ".yaml", ".yml", ".toml", ".sql", ".txt"}


def _demo() -> Any:
    spec = importlib.util.spec_from_file_location("masar_demo", ROOT / "scripts" / "demo.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_demo_page_is_what_the_demo_prints_today() -> None:
    """docs/demo.md is a transcript. If the program's output changes, the page must be written again."""
    assert (ROOT / "docs" / "demo.md").read_text(encoding="utf-8") == _demo().build(), (
        "docs/demo.md is out of date: run `uv run python scripts/demo.py`"
    )


def test_the_demo_shows_what_it_says_it_shows() -> None:
    page = (ROOT / "docs" / "demo.md").read_text(encoding="utf-8")
    assert "JOB-QUOTE requirements[4]: dropped" in page  # the made-up requirement
    assert "lowered from met by code: no fact shows: Kubernetes" in page  # the order in the posting
    assert "left out: Led the maintenance" in page and "UNSUPPORTED_TITLE: led" in page
    cv = page.split("# Sara Al-Najjar")[1].split("```")[0]
    assert "Kubernetes" not in cv
    assert "Led " not in cv
    assert "10 years" not in cv
    assert not any(line != line.rstrip() for line in page.splitlines())


def test_no_file_holds_characters_that_cannot_be_seen() -> None:
    """Control characters and the marks that reorder text have no place in source or docs."""
    problems = []
    for folder in ("src", "tests", "docs", "evals", "scripts", "examples"):
        for path in (ROOT / folder).rglob("*"):
            if path.is_file() and path.suffix in TEXT_FILES and has_unseen(path.read_text(encoding="utf-8")):
                problems.append(str(path.relative_to(ROOT)))
    assert problems == []


def test_no_real_personal_file_is_in_the_repository() -> None:
    """The career file and the watchlist of a real person live in ~/.masar, and are ignored here."""
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for name in ("/career.yaml", "/watchlist.yaml", "*.private.yaml", ".masar/"):
        assert name in ignored
    assert not (ROOT / "career.yaml").exists()
    for path in (ROOT / "evals").glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert "@" not in text.replace("sara@example.com", "")
