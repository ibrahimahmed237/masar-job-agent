"""The career file, the watchlist, exports and settings."""

from __future__ import annotations

from pathlib import Path

import pytest

from masar.adapters.clock import SystemClock
from masar.adapters.files import (
    MAX_FILE_BYTES,
    FileProblem,
    export_document,
    export_name,
    load_career,
    load_watchlist,
    read_yaml,
)
from masar.adapters.settings import DEFAULT_DAILY_TOKENS, SettingsError, load_settings
from masar.domain.job import Source
from masar.ports.sources import Board
from tests.support.career import EXAMPLE


class TestYaml:
    def test_a_missing_file_says_so(self, tmp_path: Path) -> None:
        with pytest.raises(FileProblem, match="no such file"):
            read_yaml(tmp_path / "nope.yaml")

    def test_a_syntax_error_names_the_line(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("person:\n  name: Sara\n  links: [a, b\nfacts: []\n", encoding="utf-8")
        with pytest.raises(FileProblem, match=r"bad\.yaml, line 4"):
            read_yaml(path)

    def test_a_file_that_is_too_large_is_not_read(self, tmp_path: Path) -> None:
        path = tmp_path / "big.yaml"
        path.write_bytes(b"a: " + b"x" * MAX_FILE_BYTES)
        with pytest.raises(FileProblem, match="larger than 1000 kB"):
            read_yaml(path)

    def test_only_plain_data_is_loaded(self, tmp_path: Path) -> None:
        path = tmp_path / "evil.yaml"
        path.write_text("x: !!python/object/apply:os.system ['echo no']\n", encoding="utf-8")
        with pytest.raises(FileProblem):
            read_yaml(path)


class TestCareerFile:
    def test_the_example_loads_with_a_checksum_of_its_bytes(self) -> None:
        loaded = load_career(EXAMPLE)
        assert loaded.result.ok
        assert loaded.result.unwrap().person.name == "Sara Al-Najjar"
        assert len(loaded.checksum) == 64
        assert loaded.checksum == load_career(EXAMPLE).checksum

    def test_a_changed_file_has_another_checksum(self, tmp_path: Path) -> None:
        copy = tmp_path / "career.yaml"
        copy.write_bytes(EXAMPLE.read_bytes() + b"\n# a comment\n")
        assert load_career(copy).checksum != load_career(EXAMPLE).checksum

    def test_a_file_with_faults_gives_findings_not_an_exception(self, tmp_path: Path) -> None:
        path = tmp_path / "career.yaml"
        path.write_text("person: {name: X}\nfacts: []\n", encoding="utf-8")
        loaded = load_career(path)
        assert not loaded.result.ok
        assert loaded.result.errors


class TestWatchlist:
    def load(self, tmp_path: Path, text: str):  # type: ignore[no-untyped-def]
        path = tmp_path / "watchlist.yaml"
        path.write_text(text, encoding="utf-8")
        return load_watchlist(path)

    def test_boards_are_read(self, tmp_path: Path) -> None:
        result = self.load(
            tmp_path,
            "boards:\n"
            "  - {source: greenhouse, board: tamween, company: Tamween}\n"
            "  - {source: Lever, board: qafila, region: eu}\n"
            "  - {source: ashby, board: sanad}\n"
            "  - {source: ashby, board: sanad}\n",
        )
        assert result.unwrap() == (
            Board(Source.GREENHOUSE, "tamween", "Tamween"),
            Board(Source.LEVER, "qafila", "qafila", "eu"),
            Board(Source.ASHBY, "sanad", "sanad"),
        )

    def test_an_empty_list_is_fine(self, tmp_path: Path) -> None:
        assert self.load(tmp_path, "boards: []\n").unwrap() == ()

    @pytest.mark.parametrize(
        ("entry", "code"),
        [
            ("{source: linkedin, board: x}", "WATCHLIST-SOURCE"),
            ("{source: manual, board: x}", "WATCHLIST-SOURCE"),
            ("{source: lever}", "WATCHLIST-BOARD"),
            ("{source: lever, board: '../admin'}", "WATCHLIST-BOARD"),
            ("{source: lever, board: 'a/b'}", "WATCHLIST-BOARD"),
            ("{source: lever, board: 'https://jobs.lever.co/x'}", "WATCHLIST-BOARD"),
            ("{source: lever, board: x, region: us}", "WATCHLIST-REGION"),
            ("just-a-name", "WATCHLIST-SHAPE"),
        ],
    )
    def test_a_bad_entry_is_reported_with_its_place(self, tmp_path: Path, entry: str, code: str) -> None:
        result = self.load(tmp_path, f"boards:\n  - {{source: ashby, board: ok}}\n  - {entry}\n")
        assert [(f.code, f.path) for f in result.errors] == [(code, "boards[1]")]
        assert result.value is None

    @pytest.mark.parametrize("text", ["- a\n- b\n", "boards: tamween\n", "other: 1\n", ""])
    def test_a_file_without_a_list_of_boards(self, tmp_path: Path, text: str) -> None:
        assert [f.code for f in self.load(tmp_path, text).errors] == ["WATCHLIST-SHAPE"]


class TestExport:
    def test_the_name_is_made_of_the_company_the_kind_and_the_language(self) -> None:
        assert export_name("Tamween", "cv", "en") == "tamween-cv-en.md"
        assert export_name("Al-Futtaim Group (UAE)", "cover", "ar") == "al-futtaim-group-uae-cover-ar.md"
        assert export_name("../../etc/passwd", "cv", "en") == "etc-passwd-cv-en.md"
        assert export_name("شركة", "cv", "ar") == "document-cv-ar.md"

    def test_a_document_is_written_into_a_new_folder(self, tmp_path: Path) -> None:
        target = export_document(tmp_path / "out" / "deep", "x-cv-en.md", "# نص\n")
        assert target == tmp_path / "out" / "deep" / "x-cv-en.md"
        assert target.read_text(encoding="utf-8") == "# نص\n"

    def test_an_existing_file_is_kept_unless_forced(self, tmp_path: Path) -> None:
        export_document(tmp_path, "x.md", "first")
        with pytest.raises(FileProblem, match="exists already"):
            export_document(tmp_path, "x.md", "second")
        assert (tmp_path / "x.md").read_text(encoding="utf-8") == "first"
        export_document(tmp_path, "x.md", "second", force=True)
        assert (tmp_path / "x.md").read_text(encoding="utf-8") == "second"

    def test_a_folder_that_cannot_be_made_is_a_file_problem(self, tmp_path: Path) -> None:
        (tmp_path / "taken").write_text("a file, not a folder", encoding="utf-8")
        with pytest.raises(FileProblem):
            export_document(tmp_path / "taken", "x.md", "text")


class TestSettings:
    def test_the_defaults(self) -> None:
        settings = load_settings({"HOME": "/home/sara"})
        assert settings.home == Path("/home/sara/.masar")
        assert settings.database == Path("/home/sara/.masar/masar.db")
        assert settings.career_file == Path("/home/sara/.masar/career.yaml")
        assert settings.watchlist_file == Path("/home/sara/.masar/watchlist.yaml")
        assert (settings.provider, settings.has_model, settings.daily_tokens) == (None, False, DEFAULT_DAILY_TOKENS)

    def test_everything_set(self) -> None:
        settings = load_settings(
            {
                "MASAR_HOME": "/data/masar",
                "MASAR_LLM_PROVIDER": " Anthropic ",
                "MASAR_LLM_MODEL": "claude-x",
                "MASAR_LLM_API_KEY": "sk-SECRET",
                "MASAR_LLM_BASE_URL": "https://proxy.test",
                "MASAR_DAILY_TOKENS": "5000",
            }
        )
        assert settings.home == Path("/data/masar")
        assert (settings.provider, settings.model, settings.base_url, settings.daily_tokens) == (
            "anthropic",
            "claude-x",
            "https://proxy.test",
            5000,
        )
        assert settings.has_model

    def test_the_key_is_never_shown(self) -> None:
        settings = load_settings(
            {"MASAR_LLM_PROVIDER": "openai", "MASAR_LLM_MODEL": "m", "MASAR_LLM_API_KEY": "sk-SECRET"}
        )
        assert "sk-SECRET" not in repr(settings)
        assert "sk-SECRET" not in str(settings.shown())
        assert settings.shown()["api_key"] == "***"
        assert load_settings({}).shown()["api_key"] is None

    @pytest.mark.parametrize(
        ("environ", "message"),
        [
            ({"MASAR_LLM_PROVIDER": "gemini"}, "must be one of: openai, anthropic"),
            ({"MASAR_LLM_PROVIDER": "openai"}, "MASAR_LLM_MODEL, MASAR_LLM_API_KEY"),
            ({"MASAR_LLM_PROVIDER": "openai", "MASAR_LLM_MODEL": "m"}, "needed too: MASAR_LLM_API_KEY"),
            ({"MASAR_DAILY_TOKENS": "lots"}, "whole number"),
            ({"MASAR_DAILY_TOKENS": "-1"}, "not be negative"),
        ],
    )
    def test_a_wrong_setting_says_which(self, environ: dict[str, str], message: str) -> None:
        with pytest.raises(SettingsError, match=message):
            load_settings(environ)

    def test_an_error_never_holds_the_key(self) -> None:
        with pytest.raises(SettingsError) as error:
            load_settings({"MASAR_LLM_PROVIDER": "nope", "MASAR_LLM_API_KEY": "sk-SECRET"})
        assert "sk-SECRET" not in str(error.value)

    def test_blank_values_count_as_not_set(self) -> None:
        settings = load_settings({"MASAR_LLM_PROVIDER": "  ", "MASAR_DAILY_TOKENS": "", "HOME": "/h"})
        assert (settings.provider, settings.daily_tokens) == (None, DEFAULT_DAILY_TOKENS)


def test_the_system_clock_gives_utc_and_goes_forward() -> None:
    clock = SystemClock()
    assert clock.now().utcoffset() is not None
    assert clock.now().utcoffset().total_seconds() == 0  # type: ignore[union-attr]
    assert clock.monotonic() <= clock.monotonic()


def test_a_password_in_the_address_of_a_model_server_is_not_shown() -> None:
    settings = load_settings(
        {
            "MASAR_LLM_PROVIDER": "openai",
            "MASAR_LLM_MODEL": "m",
            "MASAR_LLM_API_KEY": "k",
            "MASAR_LLM_BASE_URL": "https://user:PASSWORD@proxy.test/v1",
        }
    )
    assert settings.shown()["base_url"] == "https://***@proxy.test/v1"
    assert settings.base_url == "https://user:PASSWORD@proxy.test/v1"  # it is still used as given
    assert load_settings({"HOME": "/h"}).shown()["base_url"] is None
