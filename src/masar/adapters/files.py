"""The files a person writes and reads: the career file, the watchlist, and exported documents."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from masar.domain.career import checksum, parse_career
from masar.domain.findings import Finding, Result
from masar.domain.job import Source
from masar.ports.files import CareerFile, FileProblem
from masar.ports.sources import Board

__all__ = [
    "CareerFile",
    "FileProblem",
    "LocalFiles",
    "blocks_as_yaml",
    "export_document",
    "export_name",
    "load_career",
    "load_watchlist",
    "read_blocks",
]

MAX_FILE_BYTES = 1_000_000


def read_yaml(path: Path) -> tuple[Any, bytes]:
    """The content of a YAML file and its bytes. Only plain data is loaded."""
    try:
        size = path.stat().st_size
    except OSError:
        raise FileProblem(f"{path}: no such file") from None
    if size > MAX_FILE_BYTES:
        raise FileProblem(f"{path}: larger than {MAX_FILE_BYTES // 1000} kB")
    content = path.read_bytes()
    try:
        return yaml.safe_load(content), content
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        where = f", line {mark.line + 1}" if mark is not None else ""
        problem = getattr(error, "problem", None) or "not valid YAML"
        raise FileProblem(f"{path}{where}: {problem}") from None


def load_career(path: Path) -> CareerFile:
    data, content = read_yaml(path)
    return CareerFile(parse_career(data), checksum(content))


_BOARD_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_SOURCES = {Source.GREENHOUSE.value, Source.LEVER.value, Source.ASHBY.value}


def load_watchlist(path: Path) -> Result[tuple[Board, ...]]:
    """The boards to read. Every fault is reported with its place."""
    data, _ = read_yaml(path)
    entries = data.get("boards") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return Result(None, (Finding.error("WATCHLIST-SHAPE", "boards", "the watchlist needs a list named 'boards'"),))
    boards: list[Board] = []
    findings: list[Finding] = []
    for i, entry in enumerate(entries):
        path_ = f"boards[{i}]"
        if not isinstance(entry, dict):
            findings.append(Finding.error("WATCHLIST-SHAPE", path_, "an entry needs 'source' and 'board'"))
            continue
        source = str(entry.get("source", "")).strip().casefold()
        name = str(entry.get("board", "")).strip()
        if source not in _SOURCES:
            findings.append(
                Finding.error("WATCHLIST-SOURCE", path_, f"source must be one of: {', '.join(sorted(_SOURCES))}")
            )
            continue
        # The name becomes part of a URL: only what a board name can be is let through.
        if not _BOARD_NAME.match(name):
            findings.append(
                Finding.error("WATCHLIST-BOARD", path_, "board must be the short name from the board's address")
            )
            continue
        region = str(entry.get("region", "")).strip().casefold() or None
        if region not in (None, "eu"):
            findings.append(Finding.error("WATCHLIST-REGION", path_, "region can only be 'eu'"))
            continue
        company = str(entry.get("company") or name).strip()
        board = Board(Source(source), name, company, region)
        if board not in boards:
            boards.append(board)
    if findings:
        return Result(None, tuple(findings))
    return Result(tuple(boards))


def blocks_as_yaml(blocks: list[dict[str, Any]]) -> str:
    """A draft's blocks as a file the person can edit and give back with ``masar drafts edit``."""
    header = (
        "# The blocks of a draft. Change the text, remove a block, or add one, then run:\n"
        "#   masar drafts edit <id> --file <this file>\n"
        '# A block that says something about you names, in "facts", the facts of your career file it rests on.\n'
    )
    return header + yaml.safe_dump({"blocks": blocks}, allow_unicode=True, sort_keys=False, width=100)


def read_blocks(path: Path) -> Any:
    """The blocks of an edited draft, as written. Their shape is checked by the flow, not here."""
    data, _ = read_yaml(path)
    return data.get("blocks") if isinstance(data, dict) else data


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")[:40] or "document"


def export_name(company: str, kind: str, language: str) -> str:
    return f"{_slug(company)}-{kind}-{language}.md"


def export_document(folder: Path, name: str, markdown: str, *, force: bool = False) -> Path:
    """Writes a document into the folder. An existing file is kept unless ``force`` is set."""
    target = folder / name
    if target.exists() and not force:
        raise FileProblem(f"{target} exists already; use --force to replace it")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8")
    except OSError as error:
        raise FileProblem(f"{target}: {error.strerror or error}") from None
    return target


class LocalFiles:
    """The career file and the watchlist of one Masar folder, read again at every call."""

    def __init__(self, career_path: Path, watchlist_path: Path) -> None:
        self._career = career_path
        self._watchlist = watchlist_path

    def career(self) -> CareerFile:
        return load_career(self._career)

    def watchlist(self) -> Result[tuple[Board, ...]]:
        return load_watchlist(self._watchlist)
