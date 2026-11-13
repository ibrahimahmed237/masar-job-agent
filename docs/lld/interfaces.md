# Interfaces — the CLI and the MCP server

Two thin hosts over `masar.app`. Neither contains a rule.

## CLI

`masar`, built with Typer. Output is text for people, and JSON with `--json`.

| Command | Does | Model |
|---|---|---|
| `masar init` | Creates the Masar folder with a commented example career file and watchlist | No |
| `masar profile check` | Reads the career file; prints errors, warnings, years of experience and skills | No |
| `masar add --company C --title T [--url U] [--file F]` | Adds a posting from a file or standard input | No |
| `masar fetch` | Reads every board of the watchlist; saves new postings whose title passes the filter; reports per board | No |
| `masar jobs list [--status S] [--min-score N]` | Lists jobs with score, recommendation and flags | No |
| `masar jobs show <id>` | The requirements with verdicts and evidence, the flags, the findings | No |
| `masar assess <id> \| --new` | Runs the intake flow on one posting, or on every new one | Yes |
| `masar tailor <id> --doc cv\|cover\|outreach [--lang en\|ar]` | Runs the tailor flow until it waits for approval | Yes |
| `masar drafts list`, `show <id>` | Drafts with their status, dropped blocks and warnings | No |
| `masar drafts approve <id>`, `reject <id>`, `edit <id> --file F` | Continues the paused flow | No |
| `masar export <id> --out DIR` | Writes an approved document as Markdown | No |
| `masar apps list`, `move <id> <state> [--note N]`, `history <id>` | The application pipeline | No |
| `masar today` | What needs attention | No |
| `masar runs list`, `show <id>` | The trace of a run: steps, tokens, time | No |
| `masar check --facts id,id [--file F]` | Runs the claim checks on a text | No |
| `masar eval <set>` | Runs an evaluation set and saves the result | Depends on the set |

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Done |
| 1 | Done, and the answer is "no": errors in the career file, violations in a checked text, a failed run |
| 2 | Could not run: a wrong option, a missing file, no model configured, an id that does not exist |

## MCP server

`masar-mcp`, over stdio, built with the official Python SDK. An assistant can read and prepare. It cannot decide ([ADR-0003](../adr/0003-no-outside-actions.md)).

| Tool | Does | Changes data |
|---|---|---|
| `list_jobs` | Jobs with score, recommendation and flags; filters | No |
| `get_job` | One job: requirements, verdicts, evidence, flags | No |
| `add_posting` | Saves a pasted posting | Adds a posting |
| `assess_job` | Runs the intake flow | Saves the assessment; spends tokens |
| `draft_document` | Runs the tailor flow until it waits | Saves a pending draft; spends tokens |
| `list_drafts`, `get_draft` | Drafts with status, dropped blocks, warnings | No |
| `check_claims` | Runs the claim checks on a text with fact ids | No |
| `list_facts` | The facts of the career file: id, kind, text, skills. No contacts | No |
| `today` | What needs attention | No |

There is no tool to approve or reject a draft, to move an application, to export, or to fetch the watchlist. A tool's answer never contains the person's email, phone or links.

`check_claims` lets an assistant write with its own model and still be checked by Masar's code.

Two notes for whoever connects an assistant:

- Requirement texts and quotes in the answers come from postings, so they are untrusted text. The answers carry them as data fields, never as instructions.
- `assess_job` and `draft_document` spend tokens. The daily token limit is the ceiling, whatever an assistant is told to do.

## Tests

| Test | Proves |
|---|---|
| CLI, in process | Each command with files in a temporary Masar folder; exit codes; `--json`; a whole day: init, add, assess, tailor, approve, export, move |
| CLI, no model | Commands that need a model say so and exit 2; the others work |
| MCP, in-memory client | Each tool's schema and answer; the tool list has no deciding tool; no answer contains contact details |
