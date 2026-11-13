"""The command line. Every command is a few lines: read the input, call a use case, print the answer.

Exit codes: 0 done; 1 done and the answer is "no"; 2 could not run.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from masar import __version__
from masar.adapters.clock import SystemClock
from masar.adapters.evalsets import example_career, load_set, write_result
from masar.adapters.files import blocks_as_yaml, export_document, export_name, read_blocks
from masar.adapters.llm import build_model
from masar.adapters.settings import SettingsError, load_settings
from masar.adapters.wiring import open_masar
from masar.agent.prompts import PROMPT_VERSION
from masar.agent.session import ModelSession
from masar.app import views
from masar.app.errors import AppError, CareerInvalid, Refused
from masar.app.evaluation import evaluate, to_markdown
from masar.app.service import Masar
from masar.domain.claims import DocumentKind
from masar.ports.files import FileProblem
from masar.ports.model import ModelUnavailable

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Masar: collect job postings, screen and score them, and draft documents that say only what your career file says.",
)
profile_app = typer.Typer(no_args_is_help=True, help="Your career file.")
jobs_app = typer.Typer(no_args_is_help=True, help="The jobs Masar knows.")
drafts_app = typer.Typer(no_args_is_help=True, help="Drafts that wait for your decision.")
apps_app = typer.Typer(no_args_is_help=True, help="Your applications and where they stand.")
runs_app = typer.Typer(no_args_is_help=True, help="What the model was asked, and what it cost.")
app.add_typer(profile_app, name="profile")
app.add_typer(jobs_app, name="jobs")
app.add_typer(drafts_app, name="drafts")
app.add_typer(apps_app, name="apps")
app.add_typer(runs_app, name="runs")

# Tests and the demo put a model, job boards or a clock here, in place of the configured ones.
OVERRIDES: dict[str, Any] = {}

Json = Annotated[bool, typer.Option("--json", help="Print the answer as JSON.")]

OK, NO, CANNOT = 0, 1, 2


def say(text: str = "") -> None:
    typer.echo(text)


def fail(message: str, code: int = CANNOT) -> NoReturn:
    typer.echo(f"masar: {message}", err=True)
    raise typer.Exit(code)


def emit(as_json: bool, data: Any, lines: list[str]) -> None:
    if as_json:
        say(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        for line in lines:
            say(line)


@contextmanager
def masar() -> Iterator[Masar]:
    """The use cases, on the Masar folder of the environment. Turns their refusals into exit codes."""
    try:
        opened = open_masar(load_settings(os.environ), **OVERRIDES)
    except SettingsError as error:
        fail(str(error))
    try:
        yield opened.app
    except CareerInvalid as error:
        for finding in error.findings:
            typer.echo(f"  {finding.code} {finding.path}: {finding.message}", err=True)
        fail(str(error))
    except Refused as error:
        fail(str(error), NO)
    except (AppError, FileProblem, SettingsError) as error:
        fail(str(error))
    finally:
        opened.close()


def _read_text(file: Path | None) -> str:
    if file is None:
        return sys.stdin.read()
    try:
        return file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        fail(f"{file}: cannot be read as text")


def _cut(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


# Setup


@app.command()
def version() -> None:
    """Prints the version."""
    say(f"masar {__version__}")


@app.command()
def init(force: Annotated[bool, typer.Option("--force", help="Replace files that are already there.")] = False) -> None:
    """Creates your Masar folder with an example career file and watchlist."""
    try:
        settings = load_settings(os.environ)
    except SettingsError as error:
        fail(str(error))
    settings.home.mkdir(parents=True, exist_ok=True)
    templates = resources.files("masar.templates")
    for target in (settings.career_file, settings.watchlist_file):
        if target.exists() and not force:
            say(f"kept     {target}")
            continue
        target.write_text(templates.joinpath(target.name).read_text(encoding="utf-8"), encoding="utf-8")
        say(f"written  {target}")
    open_masar(settings, **OVERRIDES).close()
    say(f"ready    {settings.database}")
    say()
    say(f"Next: write your own facts into {settings.career_file}, then run: masar profile check")


@app.command()
def config(as_json: Json = False) -> None:
    """Shows the settings in use. The key is never shown."""
    try:
        settings = load_settings(os.environ)
    except SettingsError as error:
        fail(str(error))
    with masar() as use:
        used, _ = use.tokens_today()
    data = {**settings.shown(), "tokens_today": used}
    emit(as_json, data, [f"{name:<13} {value if value is not None else '-'}" for name, value in data.items()])


@profile_app.command("check")
def profile_check(as_json: Json = False) -> None:
    """Reads your career file and reports errors, warnings, your years of experience and your skills."""
    with masar() as use:
        report = use.profile()
    lines = [f"error    {f.code} {f.path}: {f.message}" for f in report.errors]
    lines += [f"warning  {f.code} {f.path}: {f.message}" for f in report.warnings]
    if report.ok:
        lines += [
            f"{report.facts} facts, {report.years} years of experience",
            "skills: " + ", ".join(report.skills),
            "The career file is good.",
        ]
    else:
        lines.append(f"{len(report.errors)} errors. Nothing is drafted or assessed until they are fixed.")
    emit(as_json, views.profile(report), lines)
    if not report.ok:
        raise typer.Exit(NO)


@app.command()
def facts(as_json: Json = False) -> None:
    """Lists the facts of your career file: what a document may say about you."""
    with masar() as use:
        listed = use.list_facts()
    lines = []
    for fact in listed:
        where = " · ".join(filter(None, (fact.org, fact.role, fact.period)))
        lines.append(f"{fact.id:<22} {fact.kind:<10} {where}")
        lines.append(f"{'':<22} {fact.text}")
        if fact.skills:
            lines.append(f"{'':<22} skills: {', '.join(fact.skills)}")
    emit(as_json, [views.fact(fact) for fact in listed], lines)


# Postings and jobs


@app.command()
def add(
    company: Annotated[str, typer.Option("--company", help="The company that posted the job.")],
    title: Annotated[str, typer.Option("--title", help="The job title.")],
    url: Annotated[str | None, typer.Option("--url", help="Where the posting is.")] = None,
    location: Annotated[str | None, typer.Option("--location", help="Where the job is.")] = None,
    file: Annotated[
        Path | None,
        typer.Option("--file", help="A text file with the posting. Without it, the text is read from standard input."),
    ] = None,
    as_json: Json = False,
) -> None:
    """Adds a posting from a file or from standard input."""
    text = _read_text(file)
    with masar() as use:
        stored, created = use.add_posting(company, title, text, url, location)
    word = "added" if created else "already known:"
    emit(
        as_json,
        {**views.posting(stored), "created": created},
        [f"{word} job {stored.id}: {stored.posting.company}, {stored.posting.title}"],
    )


@app.command()
def fetch(as_json: Json = False) -> None:
    """Reads every board of your watchlist and keeps the new postings whose title passes your filter."""
    with masar() as use:
        reports = use.fetch()
    lines = []
    for report in reports:
        name = f"{report.board.company} ({report.board.source.value})"
        if report.error:
            lines.append(f"{name:<32} could not be read: {report.error}")
        else:
            lines.append(
                f"{name:<32} {report.new} new, {report.known} known, {report.filtered} filtered by title, {report.skipped} skipped"
            )
    if not reports:
        lines.append("The watchlist has no boards.")
    emit(as_json, [views.fetch_report(report) for report in reports], lines)
    if reports and all(report.error for report in reports):
        raise typer.Exit(NO)


@jobs_app.command("list")
def jobs_list(
    status: Annotated[
        str | None, typer.Option("--status", help="new, assessed, screened, unreadable or failed.")
    ] = None,
    min_score: Annotated[int | None, typer.Option("--min-score", help="Only jobs with at least this score.")] = None,
    as_json: Json = False,
) -> None:
    """Lists jobs, best score first."""
    with masar() as use:
        jobs = use.list_jobs(status, min_score)
    lines = [f"{'id':>4}  {'score':>5}  {'advice':<6}  {'status':<10}  {'state':<12}  job"] if jobs else ["No jobs."]
    for job in jobs:
        score = "-" if job.score is None else str(job.score)
        advice = job.recommendation.value if job.recommendation else "-"
        flags = "".join(f"  [{flag.code}]" for flag in job.flags if flag.severity.value == "blocker")
        lines.append(
            f"{job.posting_id:>4}  {score:>5}  {advice:<6}  {job.status:<10}  {job.state.value:<12}  "
            f"{_cut(job.company, 24)}, {_cut(job.title, 40)}{flags}"
        )
    emit(as_json, [views.job_summary(job) for job in jobs], lines)


@jobs_app.command("show")
def jobs_show(
    job_id: Annotated[int, typer.Argument(help="The id of the job.")],
    text: Annotated[bool, typer.Option("--text", help="Also print the posting's text.")] = False,
    as_json: Json = False,
) -> None:
    """Shows one job: its requirements with verdicts and evidence, its flags, and what was dropped."""
    with masar() as use:
        detail = use.job(job_id)
    data = views.job_detail(detail)
    if text:
        data["text"] = detail.posting.posting.text
    score = "-" if data["score"] is None else data["score"]
    lines = [
        f"job {job_id}: {data['company']}, {data['title']}",
        f"status {data['status']} · score {score} · advice {data['recommendation'] or '-'} · state {data['state']}",
    ]
    if data["url"]:
        lines.append(data["url"])
    if data["stale"]:
        lines.append("Your career file has changed since this assessment. Run: masar assess " + str(job_id))
    if data["job"]:
        job = data["job"]
        places = ", ".join(" ".join(filter(None, (p["city"], p["country"]))) for p in job["locations"]) or "-"
        years = "-" if job["min_years"] is None else f"{job['min_years']}+"
        lines.append(
            f"{job['seniority']} · {job['employment']} · {job['workplace']} · {places} · years {years} · sponsorship {job['sponsorship']}"
        )
    if data["flags"]:
        lines += ["", "Flags"]
        lines += [f"  {flag['severity']:<8} {flag['code']}: {flag['message']}" for flag in data["flags"]]
    if data["requirements"]:
        lines += ["", "Requirements"]
        for item in data["requirements"]:
            lines.append(f"  {item['id']:<4} {item['kind']:<5} {item['verdict'] or '-':<8} {item['text']}")
            if item["evidence"]:
                lines.append(f"{'':<21}evidence: {', '.join(item['evidence'])}")
            if item["lowered_from"]:
                lines.append(f"{'':<21}lowered from {item['lowered_from']} by code: {item['reason']}")
            elif item["verdict"] and item["by"] == "model" and not item["skills"]:
                lines.append(f"{'':<21}by the model: code cannot check a requirement that names no technology")
    if data["findings"]:
        lines += ["", "Notes from the checks"]
        lines += [f"  {finding['code']} {finding['path']}: {finding['message']}" for finding in data["findings"]]
    if text:
        lines += ["", detail.posting.posting.text]
    emit(as_json, data, lines)


# Model runs


@app.command()
def assess(
    job_id: Annotated[int | None, typer.Argument(help="The id of the job.")] = None,
    new: Annotated[bool, typer.Option("--new", help="Assess every job that has not been read yet.")] = False,
    as_json: Json = False,
) -> None:
    """Reads a posting with the model, checks what it read, and scores the job."""
    if (job_id is None) == (not new):
        fail("give a job id, or --new")
    with masar() as use:
        results = use.assess_new() if job_id is None else [use.assess(job_id)]
    lines = []
    for result in results:
        record = result.record
        if result.reason:
            lines.append(f"job {result.posting_id}: failed ({result.reason})")
        elif record.status == "unreadable":
            lines.append(f"job {result.posting_id}: unreadable; nothing the model read is in the posting")
        else:
            score = "-" if record.score is None else record.score
            advice = record.recommendation.value if record.recommendation else "-"
            flags = "".join(f" [{flag.code}]" for flag in record.flags)
            lines.append(f"job {result.posting_id}: {record.status}, score {score}, advice {advice}{flags}")
    if not results:
        lines.append("No new jobs.")
    emit(as_json, [views.assess_result(result) for result in results], lines)
    if any(result.reason for result in results):
        raise typer.Exit(NO)


def _draft_lines(data: dict[str, Any]) -> list[str]:
    lines = [f"draft {data['id']}: {data['kind']} ({data['language']}) for job {data['job']}: {data['status']}"]
    if data["reason"]:
        lines.append(f"  reason: {data['reason']}")
    lines += [f"  warning: {warning}" for warning in data["warnings"]]
    for dropped in data["dropped"]:
        lines.append(f"  left out: {_cut(dropped['text'], 90)}")
        lines += [f"            {reason}" for reason in dropped["reasons"]]
    return lines


@app.command()
def tailor(
    job_id: Annotated[int, typer.Argument(help="The id of the job.")],
    doc: Annotated[DocumentKind, typer.Option("--doc", help="What to write.")] = DocumentKind.CV,
    lang: Annotated[str, typer.Option("--lang", help="en or ar.")] = "en",
    as_json: Json = False,
) -> None:
    """Drafts a CV, a cover letter or an outreach message for a job. The draft then waits for you."""
    with masar() as use:
        result = use.draft(job_id, doc, lang)
    data = views.draft_result(result, private=True)
    lines = _draft_lines(data)
    if result.document.status == "pending":
        number = result.document.id
        lines += [
            "",
            f"Read it: masar drafts show {number}",
            f"Then:    masar drafts approve {number}   or   reject {number}",
        ]
    emit(as_json, data, lines)
    if result.document.status != "pending":
        raise typer.Exit(NO)


# Drafts


@drafts_app.command("list")
def drafts_list(
    status: Annotated[str | None, typer.Option("--status", help="pending, approved, rejected or failed.")] = None,
    as_json: Json = False,
) -> None:
    """Lists drafts, newest first."""
    with masar() as use:
        drafts = use.list_drafts(status)
    lines = [f"{'id':>4}  {'status':<9}  {'kind':<8}  {'lang':<4}  {'job':>4}  notes"] if drafts else ["No drafts."]
    for draft in drafts:
        notes = []
        if draft.dropped:
            notes.append(f"{len(draft.dropped)} left out")
        if draft.status == "pending" and not draft.judged:
            notes.append("not judged")
        if draft.edited:
            notes.append("edited")
        lines.append(
            f"{draft.id:>4}  {draft.status:<9}  {draft.kind.value:<8}  {draft.language:<4}  {draft.posting_id:>4}  {', '.join(notes)}"
        )
    emit(as_json, [views.document(draft, private=True) for draft in drafts], lines)


@drafts_app.command("show")
def drafts_show(
    draft_id: Annotated[int, typer.Argument(help="The id of the draft.")],
    blocks: Annotated[bool, typer.Option("--blocks", help="Print the blocks as a file you can edit.")] = False,
    as_json: Json = False,
) -> None:
    """Shows a draft: its text, what was left out and why, and its warnings."""
    with masar() as use:
        draft = use.get_draft(draft_id)
    data = views.document(draft, private=True)
    if blocks and not as_json:
        say(blocks_as_yaml(data["blocks"]).rstrip("\n"))
        return
    emit(as_json, data, [*_draft_lines(data), "", draft.markdown.rstrip("\n")])


def _decide(draft_id: int, action: str, blocks: Any, as_json: bool) -> None:
    with masar() as use:
        result = use.decide(draft_id, action, blocks)
    data = views.draft_result(result, private=True)
    lines = _draft_lines(data)
    if result.problem:
        lines.append(f"  {result.problem}")
    if result.moved_to_drafted:
        lines.append(f"  job {result.document.posting_id} is now 'drafted'")
    emit(as_json, data, lines)
    if result.problem:
        raise typer.Exit(NO)


@drafts_app.command("approve")
def drafts_approve(
    draft_id: Annotated[int, typer.Argument(help="The id of the draft.")], as_json: Json = False
) -> None:
    """Approves a waiting draft. It is checked once more against your career file as it is now."""
    _decide(draft_id, "approve", None, as_json)


@drafts_app.command("reject")
def drafts_reject(draft_id: Annotated[int, typer.Argument(help="The id of the draft.")], as_json: Json = False) -> None:
    """Rejects a waiting draft."""
    _decide(draft_id, "reject", None, as_json)


@drafts_app.command("edit")
def drafts_edit(
    draft_id: Annotated[int, typer.Argument(help="The id of the draft.")],
    file: Annotated[
        Path, typer.Option("--file", help="The edited blocks, as written by: masar drafts show ID --blocks")
    ],
    as_json: Json = False,
) -> None:
    """Replaces the blocks of a waiting draft with yours. They go through the same checks."""
    try:
        blocks = read_blocks(file)
    except FileProblem as error:
        fail(str(error))
    _decide(draft_id, "edit", blocks, as_json)


@app.command()
def export(
    draft_id: Annotated[int, typer.Argument(help="The id of an approved draft.")],
    out: Annotated[Path, typer.Option("--out", help="The folder to write into.")],
    force: Annotated[bool, typer.Option("--force", help="Replace a file that is already there.")] = False,
    as_json: Json = False,
) -> None:
    """Writes an approved document as a Markdown file."""
    with masar() as use:
        document, posting = use.approved_document(draft_id)
        name = export_name(posting.posting.company, document.kind.value, document.language)
        target = export_document(out, name, document.markdown, force=force)
    emit(as_json, {"id": draft_id, "path": str(target)}, [f"written {target}"])


# Applications


@apps_app.command("list")
def apps_list(as_json: Json = False) -> None:
    """Lists your applications, the last changed first."""
    with masar() as use:
        listed = use.applications()
    lines = [f"{'id':>4}  {'state':<12}  {'since':<10}  job"] if listed else ["No applications."]
    for record, posting in listed:
        lines.append(
            f"{record.posting_id:>4}  {record.state.value:<12}  {record.updated_at.date().isoformat():<10}  "
            f"{_cut(posting.posting.company, 24)}, {_cut(posting.posting.title, 40)}"
        )
    emit(as_json, [views.application(record, posting) for record, posting in listed], lines)


@apps_app.command("move")
def apps_move(
    job_id: Annotated[int, typer.Argument(help="The id of the job.")],
    state: Annotated[
        str, typer.Argument(help="shortlisted, applied, interviewing, offer, rejected, withdrawn, skipped or found.")
    ],
    note: Annotated[str | None, typer.Option("--note", help="A note for your history.")] = None,
    as_json: Json = False,
) -> None:
    """Moves an application to another state. Only you do this: Masar never applies for you."""
    with masar() as use:
        moved = use.move_application(job_id, state, note)
        posting = use.job(job_id).posting
    emit(as_json, views.application(moved, posting), [f"job {job_id} is now '{moved.state.value}'"])


@apps_app.command("history")
def apps_history(job_id: Annotated[int, typer.Argument(help="The id of the job.")], as_json: Json = False) -> None:
    """Shows every move of one application."""
    with masar() as use:
        events = use.history(job_id)
    lines = []
    for event in events:
        note = f"  {event.note}" if event.note else ""
        lines.append(
            f"{event.at.date().isoformat()}  {event.from_state.value if event.from_state else '-':<12} -> {event.to_state.value:<12}{note}"
        )
    emit(as_json, [views.event(event) for event in events], lines)


@app.command()
def today(as_json: Json = False) -> None:
    """Shows what needs your attention."""
    reasons = {
        "draft-waiting": "a draft waits for your decision",
        "no-draft": "shortlisted, and nothing drafted yet",
        "applied-quiet": "applied, and no news",
        "interview-quiet": "interviewing, and no news",
    }
    with masar() as use:
        items = use.today()
    lines = [
        f"job {item.posting_id:<4} {_cut(item.company, 24)}, {_cut(item.title, 40)}: {reasons[item.reason.value]} ({item.days} days)"
        for item in items
    ]
    emit(as_json, [views.today_item(item) for item in items], lines or ["Nothing needs you today."])


# Runs


@runs_app.command("list")
def runs_list(
    limit: Annotated[int, typer.Option("--limit", min=1, max=200, help="How many runs.")] = 20, as_json: Json = False
) -> None:
    """Lists the latest runs with their tokens."""
    with masar() as use:
        listed = use.runs(limit)
        used, limit_today = use.tokens_today()
    lines = [f"{'run':<12}  {'kind':<6}  {'job':>4}  {'status':<8}  {'tokens':>7}  reason"] if listed else ["No runs."]
    for record in listed:
        job = "-" if record.posting_id is None else str(record.posting_id)
        lines.append(
            f"{record.id[:12]:<12}  {record.kind:<6}  {job:>4}  {record.status:<8}  {record.tokens_in + record.tokens_out:>7}  {record.reason or ''}"
        )
    lines.append(f"tokens today: {used} of {limit_today}")
    emit(
        as_json,
        {"runs": [views.run(record) for record in listed], "tokens_today": used, "daily_limit": limit_today},
        lines,
    )


@runs_app.command("show")
def runs_show(
    run_id: Annotated[str, typer.Argument(help="The id of the run, or its first characters.")],
    output: Annotated[bool, typer.Option("--output", help="Also print what the model answered at each step.")] = False,
    as_json: Json = False,
) -> None:
    """Shows the steps of one run: which model, how many tokens, how long."""
    with masar() as use:
        record, steps = use.run(run_id)
    lines = [f"run {record.id}: {record.kind}, {record.status}" + (f" ({record.reason})" if record.reason else "")]
    for step in steps:
        lines.append(
            f"  {step.step:<14} {step.model:<24} in {step.tokens_in:>6}  out {step.tokens_out:>6}  {step.duration_ms:>6} ms  prompts {step.prompt_version}"
        )
        if output:
            lines += [f"      {line}" for line in step.output.splitlines()]
    emit(as_json, views.run(record, steps), lines)


# Checking a text of your own


@app.command()
def check(
    facts: Annotated[
        str, typer.Option("--facts", help="The ids of the facts the text rests on, with commas between.")
    ] = "",
    file: Annotated[
        Path | None, typer.Option("--file", help="A text file. Without it, the text is read from standard input.")
    ] = None,
    lang: Annotated[str, typer.Option("--lang", help="en or ar.")] = "en",
    job: Annotated[
        int | None, typer.Option("--job", help="A job whose title, company and skills give the context.")
    ] = None,
    as_json: Json = False,
) -> None:
    """Runs the claim checks on a sentence or paragraph of your own. No model is asked."""
    text = _read_text(file)
    fact_ids = [part.strip() for part in facts.split(",") if part.strip()]
    with masar() as use:
        found = use.check_claims(text, fact_ids, language=lang, posting_id=job)
    lines = [f"{violation.code}: {violation.detail}" for violation in found] or [
        "The text says nothing that its facts do not."
    ]
    emit(as_json, views.violations(found), lines)
    if found:
        raise typer.Exit(NO)


# Evaluations


@app.command("eval")
def evaluate_set(
    name: Annotated[str, typer.Argument(help="claims, extraction, assessment or injection.")],
    sets: Annotated[Path, typer.Option("--sets", help="The folder with the sets.")] = Path("evals"),
    out: Annotated[Path, typer.Option("--out", help="The folder for the result file.")] = Path("evals/results"),
    judge: Annotated[
        bool, typer.Option("--judge", help="For claims: also ask the model to judge what code lets through.")
    ] = False,
    save: Annotated[bool, typer.Option("--save/--no-save", help="Write the result file.")] = True,
    as_json: Json = False,
) -> None:
    """Runs an evaluation set and writes its result. The sets are about the invented person of the example
    career file, not about you. The tokens of an evaluation do not count toward the daily limit."""
    try:
        settings = load_settings(os.environ)
        model = OVERRIDES.get("model") or (build_model(settings) if settings.has_model else None)
        clock = OVERRIDES.get("clock") or SystemClock()
        sessions = (lambda: ModelSession(model, clock, PROMPT_VERSION)) if model is not None else None
        day = clock.now().date()
        report = evaluate(name, load_set(sets, name), example_career(), day, sessions, judge=judge)
        markdown = to_markdown(report, day)
        target = write_result(out, name + ("-judge" if judge else ""), day, markdown) if save else None
    except ModelUnavailable as error:
        fail(f"the evaluation stopped: {error}")
    except (AppError, FileProblem, SettingsError) as error:
        fail(str(error))
    data = {
        "set": report.set_name,
        "cases": report.cases,
        "model": report.model,
        "tokens": report.tokens,
        "measures": [
            {"name": m.name, "hits": m.hits, "total": m.total, "lower_is_better": m.lower_is_better}
            for m in report.metrics
        ],
        "notes": report.notes,
        "path": str(target) if target else None,
    }
    emit(as_json, data, [markdown.rstrip("\n"), *(["", f"written {target}"] if target else [])])
