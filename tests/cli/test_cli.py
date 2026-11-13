"""The command line, in process: every command, its exit code, and a whole day from init to applied."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from masar.adapters.scripted import ScriptedModel
from masar.cli import main
from masar.domain.job import Posting, Source
from masar.ports.model import ModelUnavailable
from masar.ports.sources import Board
from tests.support.clock import FakeClock
from tests.support.postings import TEXT, all_supported, assessment, cover_blocks, cv_blocks, extraction
from tests.support.world import FakeBoards

OK, NO, CANNOT = 0, 1, 2


class Shell:
    """A terminal in a temporary Masar folder, with a scripted model behind it."""

    def __init__(self, home: Path, monkeypatch: pytest.MonkeyPatch, *, model: bool = True) -> None:
        self.home = home
        self.model = ScriptedModel([])
        self.boards = FakeBoards()
        self.clock = FakeClock()
        self.env: dict[str, str | None] = {"MASAR_HOME": str(home), "COLUMNS": "200"}
        overrides: dict[str, Any] = {"boards": self.boards, "clock": self.clock}
        if model:
            overrides["model"] = self.model
        monkeypatch.setattr(main, "OVERRIDES", overrides)
        self._runner = CliRunner()

    def run(self, *args: str, code: int = OK, stdin: str | None = None) -> str:
        result = self._runner.invoke(main.app, list(args), input=stdin, env=self.env)
        assert result.exit_code == code, f"{args}: exit {result.exit_code}\n{result.output}\n{result.exception!r}"
        return result.output

    def json(self, *args: str, code: int = OK, stdin: str | None = None) -> Any:
        return json.loads(self.run(*args, "--json", code=code, stdin=stdin))

    def script(self, *answers: Any) -> None:
        self.model._answers.extend(answers)

    def write(self, name: str, text: str) -> Path:
        path = self.home.parent / name
        path.write_text(text, encoding="utf-8")
        return path


@pytest.fixture
def shell(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Shell:
    made = Shell(tmp_path / "masar", monkeypatch)
    made.run("init")
    return made


def with_job(shell: Shell) -> None:
    shell.run("add", "--company", "Tamween", "--title", "Backend Engineer", stdin=TEXT)
    shell.script(extraction(), assessment())
    shell.run("assess", "1")


def with_pending_cv(shell: Shell) -> None:
    with_job(shell)
    shell.script(cv_blocks(), all_supported(0, 1, 2, 3))
    shell.run("tailor", "1", "--doc", "cv")


class TestInit:
    def test_init_writes_the_two_files_and_the_database(self, shell: Shell) -> None:
        assert (shell.home / "career.yaml").read_text(encoding="utf-8").startswith("# An example career file")
        assert "boards: []" in (shell.home / "watchlist.yaml").read_text(encoding="utf-8")
        assert (shell.home / "masar.db").exists()

    def test_a_second_init_keeps_your_files_unless_forced(self, shell: Shell) -> None:
        career = shell.home / "career.yaml"
        career.write_text("mine\n", encoding="utf-8")
        assert "kept" in shell.run("init")
        assert career.read_text(encoding="utf-8") == "mine\n"
        assert "written" in shell.run("init", "--force")
        assert career.read_text(encoding="utf-8") != "mine\n"

    def test_the_example_career_file_in_the_repository_is_the_one_init_writes(self, shell: Shell) -> None:
        example = Path(__file__).resolve().parents[2] / "examples" / "career.yaml"
        assert example.read_bytes() == (shell.home / "career.yaml").read_bytes()

    def test_the_version(self, shell: Shell) -> None:
        assert shell.run("version").startswith("masar 0.")


class TestProfile:
    def test_a_good_file(self, shell: Shell) -> None:
        output = shell.run("profile", "check")
        assert "8 facts, 5.5 years of experience" in output
        assert "The career file is good." in output
        data = shell.json("profile", "check")
        assert (data["ok"], data["years_of_experience"], data["errors"]) == (True, 5.5, [])

    def test_a_file_with_faults_exits_1_and_names_them(self, shell: Shell) -> None:
        career = shell.home / "career.yaml"
        career.write_text(career.read_text(encoding="utf-8").replace("id: bsc", "id: BSc Degree"), encoding="utf-8")
        output = shell.run("profile", "check", code=NO)
        assert "error    CAREER-ID" in output
        assert shell.json("profile", "check", code=NO)["ok"] is False

    def test_a_file_that_is_not_yaml_exits_2_with_the_line(self, shell: Shell) -> None:
        (shell.home / "career.yaml").write_text("person: [unclosed\nfacts: []\n", encoding="utf-8")
        assert "line" in shell.run("profile", "check", code=CANNOT)

    def test_the_facts_are_listed(self, shell: Shell) -> None:
        assert "acme-allocation" in shell.run("facts")
        assert shell.json("facts")[0]["id"] == "acme-allocation"


class TestAWholeDay:
    def test_from_a_pasted_posting_to_an_application(self, shell: Shell, tmp_path: Path) -> None:
        posting = shell.write("posting.txt", TEXT)
        assert "added job 1: Tamween, Backend Engineer" in shell.run(
            "add",
            "--company",
            "Tamween",
            "--title",
            "Backend Engineer",
            "--file",
            str(posting),
            "--url",
            "https://x.test/1",
        )
        assert "already known: job 1" in shell.run(
            "add", "--company", "Tamween", "--title", "Backend Engineer", stdin=TEXT
        )
        assert " new " in shell.run("jobs", "list")

        shell.script(extraction(), assessment())
        assert "job 1: assessed, score 90, advice apply" in shell.run("assess", "1")
        shown = shell.run("jobs", "show", "1")
        assert "status assessed · score 90 · advice apply · state found" in shown
        assert "mid · full-time · hybrid · Riyadh SA · years 3+ · sponsorship offered" in shown
        assert "r3   must  met      Experience with Postgres and Kafka in production" in shown
        assert "evidence: acme-allocation" in shown
        assert "by the model: code cannot check a requirement that names no technology" in shown

        shell.script(cv_blocks(), all_supported(0, 1, 2, 3))
        drafted = shell.run("tailor", "1", "--doc", "cv")
        assert "draft 1: cv (en) for job 1: pending" in drafted
        assert "masar drafts approve 1" in drafted
        assert "job 1    Tamween, Backend Engineer: a draft waits for your decision" in shell.run("today")
        assert "# Sara Al-Najjar" in shell.run("drafts", "show", "1")

        approved = shell.run("drafts", "approve", "1")
        assert "draft 1: cv (en) for job 1: approved" in approved
        assert "job 1 is now 'drafted'" in approved

        out = tmp_path / "out"
        assert "written" in shell.run("export", "1", "--out", str(out))
        written = (out / "tamween-cv-en.md").read_text(encoding="utf-8")
        assert written.startswith("# Sara Al-Najjar")
        assert "raised store availability to 93%" in written

        assert "job 1 is now 'applied'" in shell.run("apps", "move", "1", "applied", "--note", "sent by email")
        history = shell.run("apps", "history", "1")
        assert "found        -> drafted" in history
        assert "drafted      -> applied       sent by email" in history
        assert "applied" in shell.run("apps", "list")
        assert "Nothing needs you today." in shell.run("today")

        runs = shell.run("runs", "list")
        assert "intake" in runs and "tailor" in runs and "tokens today:" in runs
        run_id = shell.json("runs", "list")["runs"][0]["id"]
        steps = shell.run("runs", "show", run_id[:8], "--output")
        assert "draft" in steps and "judge" in steps and '"blocks"' in steps


class TestJobsShow:
    def test_flags_dropped_things_and_a_stale_assessment_are_shown(self, shell: Shell) -> None:
        career = shell.home / "career.yaml"
        career.write_text(
            career.read_text(encoding="utf-8").replace("countries: [SA, AE, EG]", "countries: [AE]"), encoding="utf-8"
        )
        shell.run(
            "add", "--company", "Tamween", "--title", "Backend Engineer", "--url", "https://x.test/job/1", stdin=TEXT
        )
        reading = extraction()
        reading["requirements"].append({"text": "COBOL", "kind": "must", "quote": "Ten years of COBOL are needed"})
        shell.script(reading)
        assert "job 1: screened, score -, advice skip [COUNTRY_NOT_WANTED]" in shell.run("assess", "1")

        shown = shell.run("jobs", "show", "1")
        assert "https://x.test/job/1" in shown
        assert "Flags" in shown and "blocker  COUNTRY_NOT_WANTED" in shown
        assert "Notes from the checks" in shown and "JOB-QUOTE requirements[4]" in shown
        assert "r1   must  -" in shown  # read, and not assessed
        assert "[COUNTRY_NOT_WANTED]" in shell.run("jobs", "list")

        career.write_text(career.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
        assert "Your career file has changed since this assessment. Run: masar assess 1" in shell.run(
            "jobs", "show", "1"
        )

    def test_a_lowered_verdict_says_who_lowered_it_and_why(self, shell: Shell) -> None:
        shell.run("add", "--company", "Tamween", "--title", "Backend Engineer", stdin=TEXT)
        said = assessment()
        said["assessments"][3] = {"requirement": "r4", "verdict": "met", "evidence": ["acme-allocation"]}
        shell.script(extraction(), said)
        shell.run("assess", "1")
        shown = shell.run("jobs", "show", "1", "--text")
        assert "r4   nice  missing  Experience with Kubernetes" in shown
        assert "lowered from met by code: no fact shows: Kubernetes" in shown
        assert "What we ask for" in shown


class TestJson:
    def test_every_listing_is_json_with_the_flag(self, shell: Shell) -> None:
        with_pending_cv(shell)
        assert shell.json("jobs", "list")[0]["score"] == 90
        job = shell.json("jobs", "show", "1", "--text")
        assert job["requirements"][3]["verdict"] == "missing"
        assert job["text"].startswith("Backend Engineer at Tamween")
        assert shell.json("drafts", "list")[0]["status"] == "pending"
        draft = shell.json("drafts", "show", "1")
        assert draft["markdown"].startswith("# Sara Al-Najjar")
        assert draft["blocks"][0]["facts"] == ["acme-allocation"]
        assert shell.json("apps", "list")[0]["state"] == "found"
        assert shell.json("apps", "history", "1")[0]["to"] == "found"
        assert shell.json("today")[0]["reason"] == "draft-waiting"
        assert shell.json("config")["api_key"] is None
        decided = shell.json("drafts", "approve", "1")
        assert (decided["status"], decided["moved_to_drafted"]) == ("approved", True)

    def test_a_model_command_answers_in_json_too(self, shell: Shell) -> None:
        shell.run("add", "--company", "Tamween", "--title", "Backend Engineer", stdin=TEXT)
        shell.script(extraction(), assessment(), cover_blocks(), all_supported(0, 1, 2))
        assert shell.json("assess", "1")[0]["score"] == 90
        draft = shell.json("tailor", "1", "--doc", "cover", "--lang", "en")
        assert (draft["kind"], draft["status"]) == ("cover", "pending")


class TestExitCodes:
    def test_an_id_that_does_not_exist_is_2(self, shell: Shell) -> None:
        assert "there is no job 9" in shell.run("jobs", "show", "9", code=CANNOT)
        assert "there is no draft 9" in shell.run("drafts", "show", "9", code=CANNOT)
        assert "there is no run" in shell.run("runs", "show", "abcdefgh", code=CANNOT)
        shell.run("apps", "move", "9", "applied", code=CANNOT)
        shell.run("export", "9", "--out", "/tmp/nowhere", code=CANNOT)

    def test_a_wrong_option_is_2(self, shell: Shell) -> None:
        shell.run("jobs", "list", "--nope", code=CANNOT)
        shell.run("tailor", "1", "--doc", "poem", code=CANNOT)
        shell.run("assess", code=CANNOT)
        shell.run("assess", "1", "--new", code=CANNOT)
        shell.run("jobs", "show", "one", code=CANNOT)

    def test_a_file_that_is_not_there_is_2(self, shell: Shell) -> None:
        shell.run("add", "--company", "C", "--title", "T", "--file", "/nowhere/posting.txt", code=CANNOT)
        shell.run("check", "--facts", "bsc", "--file", "/nowhere/text.txt", code=CANNOT)

    def test_a_refused_move_is_1(self, shell: Shell) -> None:
        shell.run("add", "--company", "C", "--title", "T", stdin=TEXT)
        assert "from 'found' you can move to" in shell.run("apps", "move", "1", "offer", code=NO)
        assert "set by Masar when you approve" in shell.run("apps", "move", "1", "drafted", code=NO)
        assert "'hired' is not a state" in shell.run("apps", "move", "1", "hired", code=CANNOT)

    def test_a_failed_run_is_1(self, shell: Shell) -> None:
        shell.run("add", "--company", "C", "--title", "T", stdin=TEXT)
        shell.script(ModelUnavailable("HTTP 503"))
        assert "job 1: failed (model unavailable: HTTP 503)" in shell.run("assess", "1", code=NO)
        assert "failed" in shell.run("jobs", "list")

    def test_a_draft_that_fails_is_1(self, shell: Shell) -> None:
        with_job(shell)
        shell.script(ModelUnavailable("HTTP 500"))
        output = shell.run("tailor", "1", code=NO)
        assert "failed" in output and "model unavailable: HTTP 500" in output

    def test_deciding_twice_is_1(self, shell: Shell) -> None:
        with_pending_cv(shell)
        shell.run("drafts", "reject", "1")
        assert "is rejected" in shell.run("drafts", "approve", "1", code=NO)

    def test_a_career_file_with_faults_stops_a_model_command_with_2(self, shell: Shell) -> None:
        shell.run("add", "--company", "C", "--title", "T", stdin=TEXT)
        career = shell.home / "career.yaml"
        career.write_text(career.read_text(encoding="utf-8").replace("id: bsc", "id: BSc Degree"), encoding="utf-8")
        output = shell.run("assess", "1", code=CANNOT)
        assert "CAREER-ID" in output and "masar profile check" in output

    def test_a_wrong_setting_is_2(self, shell: Shell) -> None:
        shell.env["MASAR_DAILY_TOKENS"] = "many"
        assert "whole number" in shell.run("jobs", "list", code=CANNOT)
        assert "whole number" in shell.run("init", code=CANNOT)
        assert "whole number" in shell.run("config", code=CANNOT)


class TestNoModel:
    def test_model_commands_say_what_to_set_and_the_rest_works(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        shell = Shell(tmp_path / "masar", monkeypatch, model=False)
        shell.run("init")
        shell.run("add", "--company", "Tamween", "--title", "Backend Engineer", stdin=TEXT)

        assert "MASAR_LLM_PROVIDER" in shell.run("assess", "1", code=CANNOT)
        assert "has not been read yet" in shell.run("tailor", "1", code=CANNOT)
        shell.run("jobs", "list")
        shell.run("profile", "check")
        shell.run("apps", "move", "1", "shortlisted")
        shell.run("today")
        shell.run("check", "--facts", "bsc", stdin="I hold a BSc in Computer Science.")

    def test_the_key_is_never_printed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        shell = Shell(tmp_path / "masar", monkeypatch)
        shell.env.update(MASAR_LLM_PROVIDER="openai", MASAR_LLM_MODEL="gpt-x", MASAR_LLM_API_KEY="sk-SECRET-KEY")
        shell.run("init")
        output = shell.run("config")
        assert "sk-SECRET-KEY" not in output
        assert "***" in output and "gpt-x" in output
        assert shell.json("config")["api_key"] == "***"


class TestDrafts:
    def test_an_edit_goes_out_as_a_file_and_comes_back_checked(self, shell: Shell) -> None:
        with_pending_cv(shell)
        blocks = shell.run("drafts", "show", "1", "--blocks")
        assert blocks.startswith("# The blocks of a draft.")
        edited = blocks.replace(
            "Maintained GraphQL and REST APIs for product listings in Node.js.",
            "Maintained GraphQL and REST APIs for product listings in Node.js and Rust.",
        )
        assert edited != blocks
        path = shell.write("blocks.yaml", edited)

        output = shell.run("drafts", "edit", "1", "--file", str(path))
        assert "draft 1: cv (en) for job 1: pending" in output
        assert "left out: Maintained GraphQL and REST APIs for product listings in Node.js and Rust." in output
        assert "UNSUPPORTED_SKILL: Rust" in output
        assert "edited by hand" in output
        assert "edited" in shell.run("drafts", "list")
        assert "and Rust" not in shell.json("drafts", "show", "1")["markdown"]

    def test_an_edit_that_cannot_be_used_is_1_and_changes_nothing(self, shell: Shell) -> None:
        with_pending_cv(shell)
        before = shell.json("drafts", "show", "1")
        path = shell.write("blocks.yaml", "blocks: just some words\n")
        assert "edit refused" in shell.run("drafts", "edit", "1", "--file", str(path), code=NO)
        assert shell.json("drafts", "show", "1") == before

    def test_an_edit_file_that_is_missing_or_not_yaml_is_2(self, shell: Shell) -> None:
        with_pending_cv(shell)
        shell.run("drafts", "edit", "1", "--file", "/nowhere/blocks.yaml", code=CANNOT)
        path = shell.write("blocks.yaml", "blocks: [unclosed\n")
        shell.run("drafts", "edit", "1", "--file", str(path), code=CANNOT)

    def test_dropped_blocks_are_shown_with_their_reasons(self, shell: Shell) -> None:
        with_job(shell)
        draft = cv_blocks()
        draft["blocks"][2]["text"] = "Built a receiving queue with Node.js and Kubernetes."
        shell.script(draft, all_supported(0, 1, 3), {"repairs": []}, {"repairs": []})
        output = shell.run("tailor", "1")
        assert "left out: Built a receiving queue with Node.js and Kubernetes." in output
        assert "UNSUPPORTED_SKILL: Kubernetes" in output
        assert "1 left out" in shell.run("drafts", "list", "--status", "pending")

    def test_approval_is_refused_with_1_when_the_career_file_changed(self, shell: Shell) -> None:
        with_pending_cv(shell)
        career = shell.home / "career.yaml"
        career.write_text(career.read_text(encoding="utf-8").replace(" to 93%.", "."), encoding="utf-8")
        output = shell.run("drafts", "approve", "1", code=NO)
        assert "not approved" in output and "UNSUPPORTED_NUMBER: 93" in output
        assert shell.json("drafts", "show", "1")["status"] == "pending"


class TestExport:
    def test_a_draft_that_is_not_approved_does_not_leave(self, shell: Shell, tmp_path: Path) -> None:
        with_pending_cv(shell)
        assert "only an approved document is exported" in shell.run(
            "export", "1", "--out", str(tmp_path / "out"), code=NO
        )
        assert not (tmp_path / "out").exists()

    def test_an_export_does_not_overwrite_without_force(self, shell: Shell, tmp_path: Path) -> None:
        with_pending_cv(shell)
        shell.run("drafts", "approve", "1")
        out = tmp_path / "out"
        data = shell.json("export", "1", "--out", str(out))
        assert data == {"id": 1, "path": str(out / "tamween-cv-en.md")}
        assert "exists already" in shell.run("export", "1", "--out", str(out), code=CANNOT)
        shell.run("export", "1", "--out", str(out), "--force")


class TestFetch:
    BOARD = Board(Source.GREENHOUSE, "tamween", "Tamween")

    def test_fetch_reports_each_board(self, shell: Shell) -> None:
        (shell.home / "watchlist.yaml").write_text(
            "boards:\n  - {source: greenhouse, board: tamween, company: Tamween}\n  - {source: ashby, board: sanad}\n",
            encoding="utf-8",
        )
        shell.boards.serve(
            self.BOARD,
            Posting(Source.GREENHOUSE, "Tamween", "Backend Engineer", "Text one.", external_id="tamween:1"),
            Posting(Source.GREENHOUSE, "Tamween", "Sales Manager", "Text two.", external_id="tamween:2"),
            skipped=1,
        )
        output = shell.run("fetch")
        assert "Tamween (greenhouse)" in output and "1 new, 0 known, 1 filtered by title, 1 skipped" in output
        assert "sanad (ashby)" in output and "could not be read: HTTP 404" in output
        assert shell.json("fetch")[0]["known"] == 1
        assert shell.model.calls == []

    def test_an_empty_watchlist(self, shell: Shell) -> None:
        assert "The watchlist has no boards." in shell.run("fetch")

    def test_when_every_board_fails_the_exit_code_is_1(self, shell: Shell) -> None:
        (shell.home / "watchlist.yaml").write_text("boards:\n  - {source: ashby, board: sanad}\n", encoding="utf-8")
        shell.run("fetch", code=NO)

    def test_a_watchlist_with_faults_is_2(self, shell: Shell) -> None:
        (shell.home / "watchlist.yaml").write_text("boards:\n  - {source: linkedin, board: x}\n", encoding="utf-8")
        assert "the watchlist has errors" in shell.run("fetch", code=CANNOT)


class TestAssessNew:
    def test_every_new_job_is_assessed(self, shell: Shell) -> None:
        shell.run("add", "--company", "A", "--title", "Backend Engineer", stdin=TEXT)
        shell.run("add", "--company", "B", "--title", "Backend Engineer", stdin=TEXT)
        shell.script(extraction(), assessment(), extraction(), assessment())
        output = shell.run("assess", "--new")
        assert "job 1: assessed" in output and "job 2: assessed" in output
        assert "No new jobs." in shell.run("assess", "--new")
        assert shell.run("jobs", "list", "--min-score", "95").strip() == "No jobs."
        assert "No jobs." not in shell.run("jobs", "list", "--status", "assessed")

    def test_an_unreadable_posting_says_so(self, shell: Shell) -> None:
        shell.run("add", "--company", "A", "--title", "Backend Engineer", stdin=TEXT)
        shell.script({"requirements": [{"text": "x", "quote": "words that are nowhere in it"}]})
        assert "unreadable" in shell.run("assess", "1")


class TestCheck:
    def test_an_honest_text_is_0(self, shell: Shell) -> None:
        output = shell.run("check", "--facts", "acme-allocation", stdin="I built an allocation service on Kafka.")
        assert "says nothing that its facts do not" in output

    def test_a_text_with_a_false_claim_is_1_and_names_it(self, shell: Shell) -> None:
        text = shell.write("claim.txt", "I built it in Rust and cut costs by 40%.")
        output = shell.run("check", "--facts", "acme-allocation, nimbus-apis", "--file", str(text), code=NO)
        assert "UNSUPPORTED_SKILL: Rust" in output and "UNSUPPORTED_NUMBER: 40" in output
        data = shell.json("check", "--facts", "acme-allocation", "--file", str(text), code=NO)
        assert data["ok"] is False

    def test_several_facts_are_given_with_commas(self, shell: Shell) -> None:
        text = "I built an allocation service on Kafka and maintained GraphQL APIs."
        shell.run("check", "--facts", "acme-allocation, nimbus-apis ,", stdin=text)
        assert "UNSUPPORTED_SKILL: GraphQL" in shell.run("check", "--facts", "acme-allocation", stdin=text, code=NO)

    def test_the_job_and_the_language_can_be_given(self, shell: Shell) -> None:
        with_job(shell)
        shell.run("check", "--facts", "acme-allocation", "--job", "1", stdin="At Tamween I would use my work on Kafka.")
        output = shell.run("check", "--facts", "acme-allocation", "--lang", "ar", stdin="I built it on Kafka.", code=NO)
        assert "WRONG_LANGUAGE" in output
