# Review 004 — M6: the use cases, the CLI and the MCP server

- **Date:** 2026-11-13
- **Scope:** `masar.app` (use cases, views, errors), `masar.adapters.wiring`, `masar.cli`, `masar.mcp_server`, the templates of `masar init`.
- **Method:** the [review checklist](../../CONTRIBUTING.md#review-checklist); every command and every tool run in a test on a real database; a pass with two questions, "what does an assistant get to see?" and "what happens when the process stops between two steps?"; then 42 deliberate bugs.

## Findings

| # | Area | Finding | Fix |
|---|---|---|---|
| 1 | Privacy | `get_draft` and `draft_document` were going to return the finished Markdown. A CV starts with the person's name, email and phone, so an assistant's model would have received exactly what [ADR-0009](../adr/0009-privacy.md) keeps from every model. | The view of a document takes a `private` flag. The MCP server never sets it: an assistant gets the blocks. A test runs a whole session and searches every answer for the name and the contacts. |
| 2 | Correctness | The flow is resumed first and the draft is updated second. A process that stops in between leaves a draft that says `pending` and a flow that is over, and every later decision would fail with "not paused". | When the flow is not paused, the use case reads how it ended and brings the draft in line with it. |
| 3 | Concurrency | Two terminals approving the same draft: the second update finds no pending row. The application must not be moved by the loser. | The second decision is refused before anything is moved. |
| 4 | Cost | The per-run budget (60,000 tokens) ignored the day's limit: a run started with 10 tokens left of the day could still spend 60,000. | A run gets the smaller of its budget and what the day has left. |
| 5 | Cost | `assess --new` with a provider that is down would start a failing run for every new posting. | It stops at the first run that the provider or the day's limit ends. One unreadable answer does not stop it. |
| 6 | Authority | "Only an approved document is exported" was going to be an `if` in the CLI. | It is in the use case that hands out the document. |
| 7 | Usefulness | Without a model configured, `assess` first complained about the career file. | The model is checked first: the message says which three settings are missing. |
| 8 | Usefulness | There was no way to get a draft's blocks to edit them. | `masar drafts show ID --blocks` prints them as YAML; `drafts edit ID --file` reads them back. |
| 9 | Usefulness | An assessment made with an older career file looked as current as any other. | A job is shown as stale when the career file's checksum has changed. |
| 10 | Correctness | Runs started in the same second were listed in the order of their random ids. | Listed by start time, then by order of insertion. |
| 11 | Packaging | The example career file lived only in `examples/`, which an installed package does not have, so `masar init` would fail outside the repository. | The templates are in the package. A test keeps the copy in `examples/` identical. |

## Experiments

| Result | Count |
|---|---|
| Caught by a test at once | 40 |
| Not caught, test added | 2 |

The two: the job's title and company not being given to the claim check; several fact ids on the command line.

## Checked, no finding

| Check | Result |
|---|---|
| Is there any tool that approves, rejects, edits, exports, moves or fetches? | No. The test compares the tool list with the design's, and tries two names that do not exist |
| Can an assistant spend past the daily limit? | No: the limit is in the use case |
| Does a decision ask a model? | No: the session of a decision has a model that fails if called |
| Does a host hold a rule? | No: the CLI and the server read input, call one use case, and print a view |
| Do the exit codes follow the table? | Yes: each code has tests for each kind of reason |
| Is the key printed by `config`, in text or JSON? | No |
| Does the server work as a real program? | Yes: started with the Python interpreter, asked for its tools and the facts |

## Result

Tests pass. Line coverage is 99% overall. Ruff and mypy (strict) are clean.
