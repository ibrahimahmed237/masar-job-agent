"""Comparing text that people and models write a little differently each time."""

from __future__ import annotations

import re
import unicodedata

_QUOTES = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "«": '"',
        "»": '"',
        "–": "-",
        "—": "-",
        "−": "-",
        " ": " ",
    }
)
_SPACE = re.compile(r"\s+")
_ARABIC_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_ARABIC_LETTER = re.compile(r"[ء-يٱ-ۓ]")
_LATIN_LETTER = re.compile(r"[A-Za-z]")


def normalize(text: str) -> str:
    """One form for comparing: NFKC, case folded, straight quotes and dashes, single spaces, Western digits."""
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES).translate(_ARABIC_INDIC)
    return _SPACE.sub(" ", text).strip().casefold()


def contains(haystack: str, needle: str) -> bool:
    """True when the needle is in the haystack after normalization. An empty needle is never contained."""
    wanted = normalize(needle)
    return bool(wanted) and wanted in normalize(haystack)


def western_digits(text: str) -> str:
    return text.translate(_ARABIC_INDIC)


def arabic_share(text: str) -> float:
    """The share of Arabic letters among the letters of a text. 0 for a text with no letters."""
    arabic = len(_ARABIC_LETTER.findall(text))
    latin = len(_LATIN_LETTER.findall(text))
    return arabic / (arabic + latin) if arabic + latin else 0.0
