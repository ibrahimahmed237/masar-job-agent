"""The tailor flow with a scripted model: draft, check, judge, repair, assemble, and the pause for the person."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

from masar.adapters.scripted import ScriptedModel
from masar.agent.prompts import PROMPT_VERSION
from masar.agent.session import Budget, BudgetExceeded, ModelOutputError, ModelSession
from masar.agent.tailor import (
    APPROVED,
    FAILED,
    PENDING,
    REJECTED,
    NotPaused,
    TailorDeps,
    TailorOutcome,
    build_tailor_graph,
    is_paused,
    resume_tailor,
    start_tailor,
)
from masar.domain import codec
from masar.domain.career import Career
from masar.domain.claims import DocumentKind
from masar.domain.matching import check_evidence
from masar.ports.model import ModelUnavailable
from tests.support.career import TODAY, career_with, example_career, example_data
from tests.support.clock import FakeClock
from tests.support.jobs import example_job
from tests.support.postings import TEXT, all_supported, assessment, cover_blocks, cv_blocks

JOB = example_job()


@pytest.fixture
def saver(tmp_path: Path) -> Iterator[Callable[[], SqliteSaver]]:
    """Makes checkpointers on one database file, each with its own connection, as separate processes would."""
    opened: list[sqlite3.Connection] = []

    def make() -> SqliteSaver:
        opened.append(sqlite3.connect(tmp_path / "masar.db", check_same_thread=False))
        return SqliteSaver(opened[-1])

    yield make
    for connection in opened:
        connection.close()


class Flow:
    """One tailor run in a test: the scripted model, the graph, and short ways to start and resume."""

    def __init__(
        self,
        answers: list[Any],
        *,
        career: Career | None = None,
        budget: Budget = Budget(),
        checkpointer: Any = None,
        run_id: str = "run-1",
    ) -> None:
        self.model = ScriptedModel(answers)
        self.session = ModelSession(self.model, FakeClock(), PROMPT_VERSION, budget)
        self.career = career or example_career()
        self.checkpointer: Any = checkpointer if checkpointer is not None else InMemorySaver()
        self.graph = build_tailor_graph(TailorDeps(self.session, self.career, TODAY), self.checkpointer)
        self.run_id = run_id

    def start(self, kind: DocumentKind = DocumentKind.CV, language: str = "en", assessed: bool = True) -> TailorOutcome:
        checked = check_evidence(JOB, self.career, assessment()).unwrap() if assessed else None
        return start_tailor(
            self.graph, self.run_id, kind=kind, language=language, job=JOB, assessment=checked, posting_text=TEXT
        )

    def resume(self, action: str, **more: Any) -> TailorOutcome:
        return resume_tailor(self.graph, self.run_id, {"action": action, **more})

    @property
    def steps(self) -> list[str]:
        return [step.step for step in self.session.steps]


def test_a_cv_is_drafted_checked_judged_assembled_and_then_waits() -> None:
    flow = Flow([cv_blocks(), all_supported(0, 1, 2, 3)])
    outcome = flow.start()

    assert outcome.status == PENDING
    assert outcome.judged is True
    assert outcome.warnings == ()
    assert outcome.document is not None
    assert outcome.document.dropped == ()
    markdown = outcome.document.markdown
    assert markdown.startswith("# Sara Al-Najjar")
    assert "raised store availability to 93%" in markdown
    assert "sara@example.com" in markdown  # contacts come from the career file, added by code
    assert flow.steps == ["draft", "judge"]
    assert is_paused(flow.graph, flow.run_id)


def test_nothing_is_approved_without_a_decision() -> None:
    flow = Flow([cv_blocks(), all_supported(0, 1, 2, 3)])
    assert flow.start().status == PENDING
    assert flow.resume("approve").status == APPROVED
    assert not is_paused(flow.graph, flow.run_id)


def test_a_rejected_draft_ends_the_run() -> None:
    flow = Flow([cv_blocks(), all_supported(0, 1, 2, 3)])
    flow.start()
    assert flow.resume("reject").status == REJECTED
    with pytest.raises(NotPaused):
        flow.resume("approve")  # a draft is decided once


def test_a_run_that_never_started_cannot_be_decided() -> None:
    flow = Flow([])
    with pytest.raises(NotPaused):
        flow.resume("approve")


def test_an_unknown_decision_leaves_the_draft_waiting() -> None:
    flow = Flow([cv_blocks(), all_supported(0, 1, 2, 3)])
    flow.start()
    outcome = flow.resume("publish")
    assert outcome.status == PENDING
    assert "unknown decision" in (outcome.problem or "")
    assert flow.resume("approve").status == APPROVED


def test_a_paused_draft_is_approved_after_a_restart_from_the_database_alone(saver: Callable[[], SqliteSaver]) -> None:
    first = Flow([cv_blocks(), all_supported(0, 1, 2, 3)], checkpointer=saver(), run_id="run-42")
    before = first.start()
    assert before.status == PENDING
    first.checkpointer.conn.close()

    # A new process: a new connection, a new graph object, and a model that would fail if it were asked.
    second = Flow([], checkpointer=saver(), run_id="run-42")
    assert is_paused(second.graph, "run-42")
    after = second.resume("approve")

    assert after.status == APPROVED
    assert after.document == before.document
    assert second.model.calls == []


def test_a_violation_is_sent_back_with_its_reason_and_the_second_draft_passes() -> None:
    draft = cv_blocks()
    draft["blocks"][2]["text"] = (
        "Built a receiving queue with Node.js, Redis and Kubernetes, cutting check-in time by 80%."
    )
    repair = {
        "repairs": [
            {
                "block": 2,
                "text": "Built a receiving queue with Node.js and Redis, cutting check-in time by 80%.",
                "facts": ["acme-receiving"],
            }
        ]
    }
    flow = Flow([draft, all_supported(0, 1, 3), repair, all_supported(2)])
    outcome = flow.start()

    assert flow.steps == ["draft", "judge", "repair", "judge"]
    asked = flow.model.calls[2][1].content
    assert "UNSUPPORTED_SKILL" in asked and "Kubernetes" in asked
    assert outcome.status == PENDING
    assert outcome.document is not None
    assert outcome.document.dropped == ()
    assert "Kubernetes" not in outcome.document.markdown.split("## Skills")[0]
    assert "Node.js and Redis, cutting check-in time by 80%" in outcome.document.markdown
    # The second judge call only saw the block that changed.
    assert '"block": 2' in flow.model.calls[3][1].content
    assert '"block": 0' not in flow.model.calls[3][1].content


def test_a_block_that_fails_both_repairs_is_dropped_and_listed() -> None:
    draft = cv_blocks()
    bad = "Built a receiving queue with Node.js and Kubernetes."
    draft["blocks"][2]["text"] = bad
    same = {"repairs": [{"block": 2, "text": bad, "facts": ["acme-receiving"]}]}
    flow = Flow([draft, all_supported(0, 1, 3), same, same])
    outcome = flow.start()

    assert flow.steps == ["draft", "judge", "repair", "repair"]
    assert outcome.status == PENDING
    assert outcome.document is not None
    (dropped,) = outcome.document.dropped
    assert dropped.text == bad
    assert any("UNSUPPORTED_SKILL" in reason for reason in dropped.reasons)
    # The job stays in the CV, in the words of the career file.
    assert "Built a receiving queue over WhatsApp with OCR of delivery notes" in outcome.document.markdown
    assert bad not in outcome.document.markdown


def test_a_block_the_judge_rejects_is_repaired() -> None:
    judged = all_supported(0, 1, 2, 3)
    judged["verdicts"][3] = {"block": 3, "supported": False, "reason": "The fact does not say who used the APIs."}
    repair = {
        "repairs": [
            {"block": 3, "text": "Maintained GraphQL and REST APIs for product listings.", "facts": ["nimbus-apis"]}
        ]
    }
    flow = Flow([cv_blocks(), judged, repair, all_supported(3)])
    outcome = flow.start()

    assert flow.steps == ["draft", "judge", "repair", "judge"]
    asked = flow.model.calls[2][1].content
    assert "NOT_SUPPORTED" in asked and "does not say who used" in asked
    assert outcome.judged is True
    assert outcome.document is not None
    assert outcome.document.dropped == ()


def test_the_same_words_on_other_facts_are_judged_again() -> None:
    draft = cv_blocks()
    draft["blocks"][0]["facts"] = ["nimbus-payments", "acme-allocation"]
    judged = all_supported(1, 2, 3)
    judged["verdicts"].append({"block": 0, "supported": False, "reason": "One cited fact has nothing to do with it."})
    text = draft["blocks"][0]["text"]
    flow = Flow(
        [draft, judged, {"repairs": [{"block": 0, "text": text, "facts": ["acme-allocation"]}]}, all_supported(0)]
    )
    outcome = flow.start()

    assert flow.steps == ["draft", "judge", "repair", "judge"]
    assert outcome.document is not None
    assert outcome.document.dropped == ()
    assert outcome.document.blocks[0].facts == ("acme-allocation",)


def test_a_block_the_judge_keeps_rejecting_is_dropped() -> None:
    no = {"verdicts": [{"block": 3, "supported": False, "reason": "Says more than the fact."}]}
    judged = all_supported(0, 1, 2)
    judged["verdicts"] += no["verdicts"]
    again = {
        "repairs": [
            {"block": 3, "text": "Maintained GraphQL and REST APIs for all product listings.", "facts": ["nimbus-apis"]}
        ]
    }
    again2 = {
        "repairs": [
            {"block": 3, "text": "Maintained GraphQL and REST APIs for the product listings.", "facts": ["nimbus-apis"]}
        ]
    }
    flow = Flow([cv_blocks(), judged, again, no, again2, no])
    outcome = flow.start()

    assert flow.steps == ["draft", "judge", "repair", "judge", "repair", "judge"]
    assert outcome.document is not None
    (dropped,) = outcome.document.dropped
    assert dropped.reasons == ("NOT_SUPPORTED: Says more than the fact.",)
    assert outcome.judged is True


def test_a_repair_cannot_touch_a_block_that_passed_or_turn_a_claim_into_a_plain_block() -> None:
    draft = cv_blocks()
    draft["blocks"][2]["text"] = "Built a receiving queue with Node.js and Kubernetes."
    sneaky = {
        "repairs": [
            {"block": 0, "text": "World-class engineer.", "facts": ["acme-allocation"]},
            {
                "block": 2,
                "text": "Built a receiving queue with Node.js and Kubernetes.",
                "kind": "plain",
                "section": "summary",
                "facts": [],
            },
        ]
    }
    flow = Flow([draft, all_supported(0, 1, 3), sneaky, sneaky])
    outcome = flow.start()

    assert outcome.document is not None
    assert "World-class" not in outcome.document.markdown
    assert "Backend engineer with 5 years of experience" in outcome.document.markdown
    assert [d.text for d in outcome.document.dropped] == ["Built a receiving queue with Node.js and Kubernetes."]


def test_a_repair_with_an_empty_text_removes_the_block() -> None:
    draft = cv_blocks()
    draft["blocks"][2]["text"] = "Built a receiving queue with Node.js and Kubernetes."
    flow = Flow([draft, all_supported(0, 1, 3), {"repairs": [{"block": 2, "text": ""}]}])
    outcome = flow.start()

    assert flow.steps == ["draft", "judge", "repair"]
    assert outcome.document is not None
    assert outcome.document.dropped == ()
    assert len(outcome.document.blocks) == 3


def test_a_cover_letter_with_too_few_honest_paragraphs_is_a_failed_draft() -> None:
    draft = cover_blocks()
    draft["blocks"][1]["text"] = "At Acme Retail I led a team of 12 engineers."
    draft["blocks"][2]["text"] = "I am an expert in Rust."
    nothing: dict[str, Any] = {"repairs": []}
    flow = Flow([draft, all_supported(0), nothing, nothing])
    outcome = flow.start(DocumentKind.COVER)

    assert outcome.status == FAILED
    assert outcome.document is None
    assert "only 1 of the needed 2 paragraphs" in (outcome.reason or "")
    assert not is_paused(flow.graph, flow.run_id)


def test_a_cover_letter_gets_its_greeting_and_signature_from_code() -> None:
    flow = Flow([cover_blocks(), all_supported(0, 1, 2)])
    outcome = flow.start(DocumentKind.COVER)

    assert outcome.status == PENDING
    assert outcome.judged is True
    assert outcome.document is not None
    assert outcome.document.markdown.startswith("Dear Tamween team,")
    assert "Sincerely,\nSara Al-Najjar" in outcome.document.markdown
    # A plain block is judged too: it must say nothing about the person.
    assert '"kind": "plain"' in flow.model.calls[1][1].content


def test_a_plain_block_that_speaks_about_the_person_is_caught_by_the_judge() -> None:
    draft = cover_blocks()
    soft = "I have deep experience in distributed systems and a strong record of delivery."
    draft["blocks"].append({"section": "body", "kind": "plain", "text": soft, "facts": []})
    judged = all_supported(0, 1, 2)
    judged["verdicts"].append({"block": 3, "supported": False, "reason": "It describes the candidate."})
    flow = Flow([draft, judged, {"repairs": [{"block": 3, "text": ""}]}])
    outcome = flow.start(DocumentKind.COVER)

    assert flow.steps == ["draft", "judge", "repair"]
    assert outcome.document is not None
    assert soft not in outcome.document.markdown
    assert outcome.judged is True


def test_a_repair_cannot_relabel_a_claim_as_plain() -> None:
    draft = cover_blocks()
    soft = "I have deep experience in distributed systems."
    draft["blocks"].append({"section": "body", "kind": "claim", "text": soft, "facts": []})
    relabel = {"repairs": [{"block": 3, "kind": "plain", "section": "body", "text": soft, "facts": []}]}
    flow = Flow([draft, all_supported(0, 1, 2), relabel, relabel, all_supported(3)])
    outcome = flow.start(DocumentKind.COVER)

    assert outcome.document is not None
    assert soft not in outcome.document.markdown
    (dropped,) = outcome.document.dropped
    assert dropped.reasons == ("CLAIM_WITHOUT_FACT: a claim names the facts it rests on",)


def test_a_plain_block_may_repeat_what_the_posting_says() -> None:
    draft = cover_blocks()
    draft["blocks"][0]["text"] = "Your posting asks for 3 years of backend work on the order pipeline."
    flow = Flow([draft, all_supported(0, 1, 2)])
    outcome = flow.start(DocumentKind.COVER)

    assert outcome.document is not None
    assert outcome.document.dropped == ()
    assert "asks for 3 years" in outcome.document.markdown


def test_the_draft_is_built_on_the_evidence_of_the_assessment_first() -> None:
    flow = Flow([cv_blocks(), all_supported(0, 1, 2, 3)])
    flow.start()
    facts = flow.model.calls[0][1].content.split("<facts>")[1]
    order = [facts.index(f'"id": "{name}"') for name in ("acme-allocation", "nimbus-apis", "acme-receiving", "bsc")]
    assert order == sorted(order)


class TestBudgets:
    def test_no_budget_for_the_draft_fails_the_run(self) -> None:
        flow = Flow([cv_blocks()], budget=Budget(calls=0))
        with pytest.raises(BudgetExceeded):
            flow.start()

    def test_no_budget_for_the_judge_gives_a_document_that_says_not_judged(self) -> None:
        flow = Flow([cv_blocks(), all_supported(0, 1, 2, 3)], budget=Budget(calls=1))
        outcome = flow.start()

        assert outcome.status == PENDING
        assert outcome.judged is False
        assert outcome.warnings == ("not judged: the run used up its calls",)
        assert flow.steps == ["draft"]

    def test_no_budget_for_a_repair_drops_what_failed(self) -> None:
        draft = cv_blocks()
        draft["blocks"][2]["text"] = "Built a receiving queue with Node.js and Kubernetes."
        flow = Flow([draft, all_supported(0, 1, 3), {"repairs": []}], budget=Budget(calls=2))
        outcome = flow.start()

        assert flow.steps == ["draft", "judge"]
        assert outcome.status == PENDING
        assert outcome.document is not None
        assert len(outcome.document.dropped) == 1
        assert outcome.warnings == ("repair stopped: the run used up its calls",)

    def test_when_the_judge_stops_nothing_more_is_asked_of_the_model(self) -> None:
        draft = cv_blocks()
        draft["blocks"][2]["text"] = "Built a receiving queue with Node.js and Kubernetes."
        flow = Flow([draft, all_supported(0, 1, 3), {"repairs": []}], budget=Budget(calls=1))
        outcome = flow.start()

        assert flow.steps == ["draft"]
        assert outcome.warnings == ("not judged: the run used up its calls",)
        assert outcome.document is not None
        assert len(outcome.document.dropped) == 1

    def test_when_a_repair_stops_the_judge_is_not_asked_again(self) -> None:
        draft = cv_blocks()
        draft["blocks"][2]["text"] = "Built a receiving queue with Node.js and Kubernetes."
        flow = Flow([draft, all_supported(0, 1), {"repairs": []}], budget=Budget(calls=2))
        outcome = flow.start()

        assert flow.steps == ["draft", "judge"]
        assert outcome.warnings == ("repair stopped: the run used up its calls",)
        assert outcome.judged is False  # block 3 never got its verdict

    def test_a_judge_that_cannot_be_read_does_not_lose_the_draft(self) -> None:
        flow = Flow([cv_blocks(), "I refuse", "still refusing"])
        outcome = flow.start()

        assert outcome.status == PENDING
        assert outcome.judged is False
        assert "not judged" in outcome.warnings[0]

    def test_a_draft_that_cannot_be_read_fails_the_run(self) -> None:
        flow = Flow(["nope", {"blocks": "not a list"}])
        with pytest.raises(ModelOutputError):
            flow.start()

    def test_a_provider_failure_fails_the_run(self) -> None:
        flow = Flow([cv_blocks(), ModelUnavailable("HTTP 500")])
        with pytest.raises(ModelUnavailable):
            flow.start()

    def test_a_judge_that_skips_a_block_leaves_the_document_marked(self) -> None:
        flow = Flow([cv_blocks(), all_supported(0, 1, 2)])
        outcome = flow.start()

        assert outcome.judged is False
        assert outcome.warnings == ("not judged: the reviewing model gave no verdict for some blocks",)

    def test_a_repair_that_cannot_be_read_keeps_the_draft_and_drops_what_failed(self) -> None:
        draft = cv_blocks()
        draft["blocks"][2]["text"] = "Built a receiving queue with Node.js and Kubernetes."
        flow = Flow([draft, all_supported(0, 1, 3), "no json", "none here either"])
        outcome = flow.start()

        assert outcome.status == PENDING
        assert outcome.document is not None
        assert len(outcome.document.dropped) == 1
        assert outcome.warnings == ("repair stopped: the model gave no answer that could be read",)

    def test_entries_that_are_not_objects_are_ignored(self) -> None:
        draft = cv_blocks()
        draft["blocks"][2]["text"] = "Built a receiving queue with Node.js and Kubernetes."
        judged = all_supported(0, 1, 3)
        judged["verdicts"].append("block 2 is fine")
        repair = {
            "repairs": [
                "rewrite it",
                {"block": 2, "text": 7},
                {"block": True, "text": "x"},
                {"block": 2, "text": "Built a receiving queue with Node.js."},
            ]
        }
        flow = Flow([draft, judged, repair, all_supported(2)])
        outcome = flow.start()

        assert outcome.document is not None
        assert outcome.document.dropped == ()
        assert "Built a receiving queue with Node.js." in outcome.document.markdown

    def test_a_judge_cannot_speak_for_a_block_it_was_not_asked_about(self) -> None:
        draft = cover_blocks()
        verdicts = {
            "verdicts": [
                {"block": 7, "supported": False, "reason": "x"},
                {"block": 1, "supported": "yes"},
                {"block": 0, "supported": True},
                {"block": 2, "supported": True},
            ]
        }
        flow = Flow([draft, verdicts])
        outcome = flow.start(DocumentKind.COVER)

        assert outcome.document is not None
        assert outcome.document.dropped == ()  # there is no block 7 to reject
        assert outcome.judged is False  # "yes" is not a verdict


class TestEdit:
    def start(self) -> Flow:
        flow = Flow([cover_blocks(), all_supported(0, 1, 2)])
        flow.start(DocumentKind.COVER)
        return flow

    def test_an_edit_is_checked_by_code_and_waits_again(self) -> None:
        flow = self.start()
        blocks = cover_blocks()["blocks"]
        blocks[2]["text"] = "At Nimbus Commerce I maintained GraphQL and REST APIs for product listings."
        outcome = flow.resume("edit", blocks=blocks)

        assert outcome.status == PENDING
        assert outcome.edited is True
        assert outcome.judged is False
        assert outcome.warnings == ("edited by hand: checked by code, not judged by a model",)
        assert outcome.document is not None
        assert "At Nimbus Commerce I maintained" in outcome.document.markdown
        assert flow.model.calls == flow.model.calls[:2]  # an edit asks no model
        assert flow.resume("approve").status == APPROVED

    def test_an_edit_cannot_bring_in_a_claim_either(self) -> None:
        flow = self.start()
        blocks = cover_blocks()["blocks"]
        blocks.append(
            {"section": "body", "kind": "claim", "text": "I am also an expert in Rust.", "facts": ["nimbus-apis"]}
        )
        outcome = flow.resume("edit", blocks=blocks)

        assert outcome.document is not None
        assert "Rust" not in outcome.document.markdown
        (dropped,) = outcome.document.dropped
        assert any("UNSUPPORTED_SKILL: Rust" in reason for reason in dropped.reasons)

    def test_an_edit_that_leaves_too_little_is_refused_and_the_draft_stays(self) -> None:
        flow = self.start()
        outcome = flow.resume("edit", blocks=[{"section": "body", "kind": "plain", "text": "Hello.", "facts": []}])

        assert outcome.status == PENDING
        assert "edit refused" in (outcome.problem or "")
        assert outcome.edited is False
        assert outcome.document is not None
        assert "raised store availability to 93%" in outcome.document.markdown

    def test_an_edit_that_is_not_blocks_is_refused(self) -> None:
        flow = self.start()
        outcome = flow.resume("edit", blocks="a new letter, as one text")
        assert "edit refused" in (outcome.problem or "")
        assert outcome.status == PENDING

    def test_a_good_decision_clears_the_problem_of_the_one_before(self) -> None:
        flow = self.start()
        assert flow.resume("edit", blocks=[]).problem
        assert flow.resume("approve").problem is None


def test_approval_is_refused_when_the_career_file_no_longer_supports_the_draft(
    saver: Callable[[], SqliteSaver],
) -> None:
    first = Flow([cv_blocks(), all_supported(0, 1, 2, 3)], checkpointer=saver())
    assert first.start().status == PENDING
    first.checkpointer.conn.close()

    # The person takes the 93% out of the career file, then approves the old draft.
    data = example_data()
    data["facts"][0]["text"] = "Built an event-driven inventory allocation service."
    second = Flow([], career=career_with(facts=data["facts"]), checkpointer=saver())
    outcome = second.resume("approve")

    assert outcome.status == PENDING
    assert "not approved" in (outcome.problem or "")
    assert "UNSUPPORTED_NUMBER: 93" in (outcome.problem or "")
    assert second.resume("reject").status == REJECTED


def test_an_arabic_letter_is_checked_as_arabic() -> None:
    draft = {
        "blocks": [
            {
                "section": "body",
                "kind": "plain",
                "text": "أكتب إليكم بخصوص وظيفة Backend Engineer في Tamween.",
                "facts": [],
            },
            {
                "section": "body",
                "kind": "claim",
                "text": "في Acme Retail بنيت خدمة لتوزيع المخزون باستخدام Kafka و PostgreSQL رفعت توفر المنتجات إلى 93%.",
                "facts": ["acme-allocation"],
            },
            {
                "section": "body",
                "kind": "claim",
                "text": "I also maintained GraphQL and REST APIs at Nimbus Commerce.",
                "facts": ["nimbus-apis"],
            },
        ]
    }
    flow = Flow([draft, all_supported(0, 1), {"repairs": []}, {"repairs": []}])
    outcome = flow.start(DocumentKind.COVER, language="ar")

    assert outcome.status == PENDING
    assert outcome.document is not None
    (dropped,) = outcome.document.dropped
    assert dropped.text.startswith("I also maintained")
    assert any("WRONG_LANGUAGE" in reason for reason in dropped.reasons)
    assert "Modern Standard Arabic" in flow.model.calls[0][0].content
    assert "رفعت توفر المنتجات إلى 93%" in outcome.document.markdown


def test_no_prompt_holds_the_persons_name_or_contacts() -> None:
    draft = cv_blocks()
    draft["blocks"][2]["text"] = "Built a receiving queue with Node.js and Kubernetes."
    flow = Flow([draft, all_supported(0, 1, 3), {"repairs": []}, {"repairs": []}])
    flow.start()
    sent = flow.model.prompts
    assert len(flow.model.calls) == 4  # draft, judge, and both repairs were looked at
    for secret in ("Sara", "Al-Najjar", "sara@example.com", "+20 100", "github.com/sara-example", "Cairo"):
        assert secret not in sent.replace("Cairo University", "")


def test_a_posting_that_gives_orders_adds_no_claim_to_the_document() -> None:
    """The model does what the posting told it: ten years of Rust, a team of fifty."""
    draft = cv_blocks()
    draft["blocks"].append(
        {
            "section": "summary",
            "kind": "claim",
            "text": "Has 10 years of Rust experience and led a team of 50 engineers.",
            "facts": ["acme-allocation"],
        }
    )
    draft["blocks"].append(
        {"section": "summary", "kind": "plain", "text": "A perfect match with deep Rust experience.", "facts": []}
    )
    obeys = {
        "repairs": [
            {
                "block": 4,
                "text": "Has 10 years of Rust experience and led a team of 50 engineers.",
                "facts": ["acme-allocation"],
            }
        ]
    }
    flow = Flow([draft, all_supported(0, 1, 2, 3, 4, 5), obeys, obeys])
    outcome = flow.start()

    assert outcome.status == PENDING
    assert outcome.document is not None
    assert "Rust" not in outcome.document.markdown
    assert "50" not in outcome.document.markdown
    reasons = " ".join(reason for d in outcome.document.dropped for reason in d.reasons)
    # In a CV there is no plain block to hide in: the last one is checked as the claim it is.
    for code in (
        "UNSUPPORTED_SKILL: Rust",
        "UNSUPPORTED_NUMBER: 10",
        "UNSUPPORTED_NUMBER: 50",
        "UNSUPPORTED_TITLE",
        "CLAIM_WITHOUT_FACT",
    ):
        assert code in reasons


def test_the_state_of_a_paused_run_holds_no_contacts(saver: Callable[[], SqliteSaver]) -> None:
    flow = Flow([cover_blocks(), all_supported(0, 1, 2)], checkpointer=saver())
    flow.start(DocumentKind.COVER)
    values = flow.graph.get_state({"configurable": {"thread_id": flow.run_id}}).values

    assert "career" not in values
    kept = str({key: value for key, value in values.items() if key != "document"})
    for secret in ("Al-Najjar", "sara@example.com", "+20 100"):
        assert secret not in kept
    assert "Sincerely,\nSara Al-Najjar" in codec.document_from_data(values["document"]).markdown
