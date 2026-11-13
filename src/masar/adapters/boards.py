"""Job boards with a public JSON API (ADR-0004): one GET per board, read defensively."""

from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote

import httpx

from masar import __version__
from masar.domain.job import Posting, Source
from masar.ports.sources import Board, FetchResult

USER_AGENT = f"masar/{__version__} (personal job-search tool)"
TIMEOUT_SECONDS = 20.0
MAX_BYTES = 5_000_000
MIN_TEXT = 200

_BLOCK_TAGS = frozenset(
    {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "section", "article"}
)
_SKIPPED_TAGS = frozenset({"script", "style", "head", "template", "noscript"})


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_TAGS:
            self._skipping += 1
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS:
            self._skipping = max(0, self._skipping - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    """Plain text from HTML: tags gone, blocks and list items on their own lines, white space tidied."""
    parser = _Text()
    parser.feed(markup)
    parser.close()
    text = "".join(parser.parts).replace("\xa0", " ")
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n")]
    lines = [line for line in lines if line not in ("", "-")]
    return "\n".join(lines)


def _str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


class _Unexpected(Exception):
    """The answer is JSON, but not the JSON this board should give."""


def _greenhouse(body: Any, board: Board) -> tuple[list[Posting], int]:
    jobs = body.get("jobs") if isinstance(body, dict) else None
    if not isinstance(jobs, list):
        raise _Unexpected
    postings, skipped = [], 0
    for job in jobs:
        if not isinstance(job, dict):
            skipped += 1
            continue
        location = job.get("location")
        # The API escapes its HTML once more: unescape first, then read the HTML.
        text = html_to_text(html.unescape(_str(job.get("content"))))
        title = _str(job.get("title"))
        if not title or len(text) < MIN_TEXT or job.get("id") is None:
            skipped += 1
            continue
        postings.append(
            Posting(
                source=Source.GREENHOUSE,
                company=board.company,
                title=title,
                text=text,
                url=_str(job.get("absolute_url")) or None,
                location=(_str(location.get("name")) or None) if isinstance(location, dict) else None,
                external_id=f"{board.board}:{job['id']}",
            )
        )
    return postings, skipped


def _lever(body: Any, board: Board) -> tuple[list[Posting], int]:
    if not isinstance(body, list):
        raise _Unexpected
    postings, skipped = [], 0
    for job in body:
        if not isinstance(job, dict):
            skipped += 1
            continue
        raw_categories = job.get("categories")
        categories: dict[str, Any] = raw_categories if isinstance(raw_categories, dict) else {}
        parts = [_str(job.get("descriptionPlain"))]
        lists = job.get("lists")
        for section in lists if isinstance(lists, list) else []:
            if isinstance(section, dict):
                parts += [_str(section.get("text")), html_to_text(_str(section.get("content")))]
        parts.append(_str(job.get("additionalPlain")))
        if workplace := _str(job.get("workplaceType")):
            parts.append(f"Workplace: {workplace}")
        if commitment := _str(categories.get("commitment")):
            parts.append(f"Commitment: {commitment}")
        text = "\n".join(part for part in parts if part)
        title = _str(job.get("text"))
        if not title or len(text) < MIN_TEXT or not _str(job.get("id")):
            skipped += 1
            continue
        postings.append(
            Posting(
                source=Source.LEVER,
                company=board.company,
                title=title,
                text=text,
                url=_str(job.get("hostedUrl")) or None,
                location=_str(categories.get("location")) or None,
                external_id=f"{board.board}:{_str(job.get('id'))}",
            )
        )
    return postings, skipped


def _ashby(body: Any, board: Board) -> tuple[list[Posting], int]:
    jobs = body.get("jobs") if isinstance(body, dict) else None
    if not isinstance(jobs, list):
        raise _Unexpected
    postings, skipped = [], 0
    for job in jobs:
        if not isinstance(job, dict):
            skipped += 1
            continue
        if job.get("isListed") is False:
            continue  # not an open posting: neither read nor counted as skipped
        parts = [_str(job.get("descriptionPlain"))]
        if employment := _str(job.get("employmentType")):
            parts.append(f"Employment type: {employment}")
        if workplace := _str(job.get("workplaceType")):
            parts.append(f"Workplace: {workplace}")
        if isinstance(job.get("isRemote"), bool):
            parts.append(f"Remote: {'yes' if job['isRemote'] else 'no'}")
        text = "\n".join(part for part in parts if part)
        title = _str(job.get("title"))
        if not title or len(_str(job.get("descriptionPlain"))) < MIN_TEXT or not _str(job.get("id")):
            skipped += 1
            continue
        postings.append(
            Posting(
                source=Source.ASHBY,
                company=board.company,
                title=title,
                text=text,
                url=_str(job.get("jobUrl")) or None,
                location=_str(job.get("location")) or None,
                external_id=f"{board.board}:{_str(job.get('id'))}",
            )
        )
    return postings, skipped


_READERS = {Source.GREENHOUSE: _greenhouse, Source.LEVER: _lever, Source.ASHBY: _ashby}


def board_url(board: Board) -> str:
    name = quote(board.board, safe="")
    if board.source is Source.GREENHOUSE:
        return f"https://boards-api.greenhouse.io/v1/boards/{name}/jobs?content=true"
    if board.source is Source.LEVER:
        host = "api.eu.lever.co" if board.region == "eu" else "api.lever.co"
        return f"https://{host}/v0/postings/{name}?mode=json"
    if board.source is Source.ASHBY:
        return f"https://api.ashbyhq.com/posting-api/job-board/{name}"
    raise ValueError(f"{board.source} is not a job board")


class HttpJobBoards:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT})

    def close(self) -> None:
        self._client.close()

    def fetch(self, board: Board) -> FetchResult:
        try:
            body = self._get(board_url(board))
        except httpx.TimeoutException:
            return FetchResult(board, error="no answer in time")
        except httpx.HTTPError as error:
            return FetchResult(board, error=f"could not be reached ({type(error).__name__})")
        except _Unexpected as error:
            return FetchResult(board, error=str(error))
        try:
            postings, skipped = _READERS[board.source](body, board)
        except _Unexpected:
            return FetchResult(board, error="the answer does not look like this board's list of jobs")
        return FetchResult(board, tuple(postings), skipped)

    def _get(self, url: str) -> Any:
        with self._client.stream(
            "GET", url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
        ) as answer:
            if answer.status_code != 200:
                raise _Unexpected(f"HTTP {answer.status_code}")
            content = bytearray()
            for chunk in answer.iter_bytes():
                content += chunk
                if len(content) > MAX_BYTES:
                    raise _Unexpected(f"the answer is larger than {MAX_BYTES // 1_000_000} MB")
        try:
            return json.loads(content)
        except ValueError:
            raise _Unexpected("the answer is not JSON") from None
