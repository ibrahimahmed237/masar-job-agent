"""How the languages a person speaks are written, in the two languages of the documents."""

from __future__ import annotations

LANGUAGE_NAMES: dict[str, dict[str, str]] = {
    "en": {
        "ar": "Arabic",
        "en": "English",
        "fr": "French",
        "de": "German",
        "es": "Spanish",
        "tr": "Turkish",
        "ur": "Urdu",
    },
    "ar": {
        "ar": "العربية",
        "en": "الإنجليزية",
        "fr": "الفرنسية",
        "de": "الألمانية",
        "es": "الإسبانية",
        "tr": "التركية",
        "ur": "الأردية",
    },
}
