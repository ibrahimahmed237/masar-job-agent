"""The example career file, loaded once, and helpers to change one thing in it."""

from __future__ import annotations

import copy
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from masar.domain.career import Career, parse_career

EXAMPLE = Path(__file__).resolve().parents[2] / "src" / "masar" / "templates" / "career.yaml"
TODAY = date(2026, 11, 13)


@cache
def _data() -> dict[str, Any]:
    loaded = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def example_data() -> dict[str, Any]:
    """A fresh copy of the example file's content, safe to change."""
    return copy.deepcopy(_data())


def example_career() -> Career:
    return parse_career(example_data()).unwrap()


def career_with(**changes: Any) -> Career:
    """The example career with top-level sections replaced or merged: ``career_with(limits={"remote": False})``."""
    data = example_data()
    for section, value in changes.items():
        if isinstance(value, dict) and isinstance(data.get(section), dict):
            data[section].update(value)
        else:
            data[section] = value
    return parse_career(data).unwrap()
