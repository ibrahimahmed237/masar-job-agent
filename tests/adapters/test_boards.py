"""The three job-board clients against answers in the shape of the real APIs, and against bad answers."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from masar.adapters.boards import MAX_BYTES, USER_AGENT, HttpJobBoards, board_url, html_to_text
from masar.domain.job import Source
from masar.ports.sources import Board

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

GREENHOUSE = Board(Source.GREENHOUSE, "tamween", "Tamween")
LEVER = Board(Source.LEVER, "qafila", "Qafila")
ASHBY = Board(Source.ASHBY, "sanad", "Sanad")


def boards(handler: Callable[[httpx.Request], httpx.Response]) -> HttpJobBoards:
    return HttpJobBoards(httpx.Client(transport=httpx.MockTransport(handler)))


def serving(name: str, seen: list[httpx.Request] | None = None) -> HttpJobBoards:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, content=(FIXTURES / name).read_bytes(), headers={"content-type": "application/json"})

    return boards(handler)


class TestHtmlToText:
    def test_blocks_and_list_items_get_their_own_lines(self) -> None:
        text = html_to_text("<h2>Ask</h2><ul><li>One</li><li>Two &amp; three</li></ul><p>End<br>here</p>")
        assert text == "Ask\n- One\n- Two & three\nEnd\nhere"

    def test_scripts_and_styles_are_left_out(self) -> None:
        assert html_to_text("<style>p{}</style><p>Kept</p><script>steal()</script>") == "Kept"

    def test_white_space_is_tidied(self) -> None:
        assert html_to_text("<p>  A&nbsp;&nbsp;b \t c </p>\n\n\n<p></p><p>d</p>") == "A b c\nd"

    def test_plain_text_passes_through(self) -> None:
        assert html_to_text("Just words") == "Just words"

    def test_inline_tags_do_not_break_a_line(self) -> None:
        assert html_to_text("<p>Build <strong>fast</strong> services</p>") == "Build fast services"


class TestGreenhouse:
    def test_a_job_is_mapped(self) -> None:
        seen: list[httpx.Request] = []
        result = serving("greenhouse.json", seen).fetch(GREENHOUSE)

        assert result.error is None
        (posting,) = result.postings
        assert (posting.source, posting.company, posting.title) == (Source.GREENHOUSE, "Tamween", "Backend Engineer")
        assert posting.external_id == "tamween:4011223"
        assert posting.url == "https://boards.greenhouse.io/tamween/jobs/4011223"
        assert posting.location == "Riyadh, Saudi Arabia"
        # The escaped HTML became text: lists as lines, entities as characters, no script.
        assert "- Build and run backend services in Node.js & TypeScript" in posting.text
        assert "- 3+ years of experience building backend services" in posting.text
        assert "We offer visa sponsorship. This is a full-time position in Riyadh." in posting.text
        assert "<" not in posting.text
        assert "alert" not in posting.text

    def test_thin_untitled_and_broken_jobs_are_counted_as_skipped(self) -> None:
        assert serving("greenhouse.json").fetch(GREENHOUSE).skipped == 3

    def test_one_request_with_a_named_user_agent(self) -> None:
        seen: list[httpx.Request] = []
        serving("greenhouse.json", seen).fetch(GREENHOUSE)
        (request,) = seen
        assert str(request.url) == "https://boards-api.greenhouse.io/v1/boards/tamween/jobs?content=true"
        assert request.method == "GET"
        assert request.headers["user-agent"] == USER_AGENT
        assert "personal job-search tool" in USER_AGENT


class TestLever:
    def test_a_job_is_mapped_with_its_lists(self) -> None:
        result = serving("lever.json").fetch(LEVER)

        assert result.error is None
        assert result.skipped == 2
        (posting,) = result.postings
        assert (posting.source, posting.company, posting.title) == (Source.LEVER, "Qafila", "Platform Engineer")
        assert posting.external_id == "qafila:7a1c0f1e-1111-4222-8333-944455556666"
        assert posting.location == "Dubai"
        assert posting.url == "https://jobs.lever.co/qafila/7a1c0f1e-1111-4222-8333-944455556666"
        lines = posting.text.split("\n")
        assert lines[0].startswith("Qafila moves freight across the Gulf.")
        assert lines[1:] == [
            "Requirements",
            "- 5+ years with Go or Java",
            "- Kubernetes in production",
            "Nice to have",
            "- Terraform",
            "We sponsor visas for this role.",
            "Workplace: hybrid",
            "Commitment: Full-time",
        ]

    def test_the_european_service_has_its_own_address(self) -> None:
        assert board_url(LEVER) == "https://api.lever.co/v0/postings/qafila?mode=json"
        eu = Board(Source.LEVER, "qafila", "Qafila", region="eu")
        assert board_url(eu) == "https://api.eu.lever.co/v0/postings/qafila?mode=json"


class TestAshby:
    def test_a_listed_job_is_mapped(self) -> None:
        seen: list[httpx.Request] = []
        result = serving("ashby.json", seen).fetch(ASHBY)

        assert str(seen[0].url) == "https://api.ashbyhq.com/posting-api/job-board/sanad"
        assert result.error is None
        (posting,) = result.postings
        assert (posting.source, posting.company, posting.title) == (Source.ASHBY, "Sanad", "AI Engineer")
        assert posting.external_id == "sanad:c0ffee00-1234-4abc-9def-000011112222"
        assert posting.location == "Cairo"
        assert posting.text.endswith("Employment type: FullTime\nWorkplace: Remote\nRemote: yes")

    def test_an_unlisted_job_is_not_read_and_a_thin_one_is_skipped(self) -> None:
        result = serving("ashby.json").fetch(ASHBY)
        assert [p.title for p in result.postings] == ["AI Engineer"]
        assert result.skipped == 1


class TestBadAnswers:
    @pytest.mark.parametrize("status", [301, 404, 429, 500])
    def test_an_http_error_is_an_error_for_that_board(self, status: int) -> None:
        result = boards(lambda request: httpx.Response(status, json={"jobs": []})).fetch(GREENHOUSE)
        assert result.error == f"HTTP {status}"
        assert result.postings == ()

    def test_a_timeout_is_an_error_for_that_board(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow", request=request)

        assert boards(handler).fetch(LEVER).error == "no answer in time"

    def test_a_network_failure_is_an_error_for_that_board(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        assert boards(handler).fetch(ASHBY).error == "could not be reached (ConnectError)"

    def test_a_body_that_is_not_json(self) -> None:
        result = boards(lambda request: httpx.Response(200, text="<html>Sign in</html>")).fetch(GREENHOUSE)
        assert result.error == "the answer is not JSON"

    @pytest.mark.parametrize(
        ("board", "body"),
        [
            (GREENHOUSE, []),
            (GREENHOUSE, {"jobs": "many"}),
            (LEVER, {"jobs": []}),
            (ASHBY, {"postings": []}),
            (ASHBY, None),
        ],
    )
    def test_json_of_another_shape(self, board: Board, body: object) -> None:
        result = boards(lambda request: httpx.Response(200, content=json.dumps(body))).fetch(board)
        assert result.error == "the answer does not look like this board's list of jobs"

    def test_a_body_that_is_too_large_is_not_read_to_the_end(self) -> None:
        big = b'{"jobs": [' + b" " * (MAX_BYTES + 10) + b"]}"
        result = boards(lambda request: httpx.Response(200, content=big)).fetch(GREENHOUSE)
        assert result.error == "the answer is larger than 5 MB"

    def test_an_empty_board_is_not_an_error(self) -> None:
        result = boards(lambda request: httpx.Response(200, json={"jobs": []})).fetch(GREENHOUSE)
        assert (result.error, result.postings, result.skipped) == (None, (), 0)

    def test_odd_fields_do_not_break_the_reading(self) -> None:
        body = [
            {"id": "1", "text": "Engineer", "categories": "none", "lists": "none", "descriptionPlain": "z" * 250},
            {"id": "2", "text": 7, "descriptionPlain": "z" * 250},
            {"id": "3", "text": "Engineer", "descriptionPlain": None, "lists": [None, {"text": "Ask", "content": 5}]},
        ]
        result = boards(lambda request: httpx.Response(200, json=body)).fetch(LEVER)
        assert [p.external_id for p in result.postings] == ["qafila:1"]
        assert result.postings[0].location is None
        assert result.skipped == 2

    def test_entries_that_are_not_jobs_are_skipped_on_every_board(self) -> None:
        lever = boards(lambda request: httpx.Response(200, json=["x", 3])).fetch(LEVER)
        ashby = boards(lambda request: httpx.Response(200, json={"jobs": ["x", None]})).fetch(ASHBY)
        assert (lever.skipped, ashby.skipped, lever.error, ashby.error) == (2, 2, None, None)

    def test_pasted_postings_have_no_board_to_read(self) -> None:
        with pytest.raises(ValueError, match="not a job board"):
            board_url(Board(Source.MANUAL, "x", "X"))

    def test_the_default_client_has_a_timeout_and_can_be_closed(self) -> None:
        reader = HttpJobBoards()
        assert reader._client.timeout == httpx.Timeout(20.0)
        reader.close()
        assert reader._client.is_closed

    def test_a_board_name_cannot_change_the_address(self) -> None:
        odd = Board(Source.GREENHOUSE, "../../v2/secret?x=1#", "X")
        assert (
            board_url(odd)
            == "https://boards-api.greenhouse.io/v1/boards/..%2F..%2Fv2%2Fsecret%3Fx%3D1%23/jobs?content=true"
        )
