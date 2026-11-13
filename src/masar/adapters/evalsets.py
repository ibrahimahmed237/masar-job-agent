"""Evaluation sets on disk, and the result files."""

from __future__ import annotations

import json
from datetime import date
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from masar.domain.career import Career, parse_career
from masar.ports.files import FileProblem

MAX_SET_BYTES = 5_000_000


def load_set(folder: Path, name: str) -> Any:
    path = folder / f"{name}.json"
    try:
        if path.stat().st_size > MAX_SET_BYTES:
            raise FileProblem(f"{path}: larger than {MAX_SET_BYTES // 1_000_000} MB")
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise FileProblem(f"{path}: no such file") from None
    except ValueError as error:
        raise FileProblem(f"{path}: not valid JSON ({error})") from None


def write_result(folder: Path, name: str, day: date, markdown: str) -> Path:
    path = folder / f"{name}-{day.isoformat()}.md"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
    except OSError as error:
        raise FileProblem(f"{path}: {error.strerror or error}") from None
    return path


def example_career() -> Career:
    """The invented person the sets are written about: the career file that ``masar init`` writes."""
    text = resources.files("masar.templates").joinpath("career.yaml").read_text(encoding="utf-8")
    return parse_career(yaml.safe_load(text)).unwrap()
