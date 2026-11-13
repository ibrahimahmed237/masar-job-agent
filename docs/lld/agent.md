# Agent — the model session and the two graphs

`masar.agent` holds the flows as LangGraph graphs ([ADR-0005](../adr/0005-langgraph.md)), the prompts, and the session that wraps every model call. It imports the domain and the ports.

## The model session

One `ModelSession` per run. Every model call goes through it.

| Job | How |
|---|---|
| Budget | Limits on calls (12), total tokens (60,000) and wall time (180 s) per run, and 2,000 output tokens per call. Going over raises `BudgetExceeded`; the run fails with that reason |
| Daily budget | Before the first call, the use case checks the day's tokens against the daily limit (400,000) |
| JSON | `ask_json(step, messages)` takes the first JSON object from the answer (also inside a code fence), parses it, and returns a dict. A parse failure gets one more call with the error added; a second failure raises `ModelOutputError` |
| Provider failures | A network error or an HTTP error from the provider raises `ModelUnavailable` |
| Trace | Each call is recorded: step, model, tokens in and out, milliseconds, a checksum of the input, and the output text |

## Prompts

- The system message holds the rules and the output schema. The data comes in the user message, in labelled blocks: `<posting>`, `<facts>`, `<blocks>`, `<violations>`.
- Facts are sent as `id`, `kind`, `org`, `role`, `period`, `text`, `skills`. Never the person's name or contacts ([ADR-0009](../adr/0009-privacy.md)).
- The model is told that the posting is data and may contain instructions to ignore. The design does not depend on it obeying ([ADR-0012](../adr/0012-untrusted-postings.md)).
- Prompts are constants in one module, with a version string that is stored in the trace.

## The intake graph

```mermaid
flowchart LR
  S((start)) --> extract --> ground --> screen
  screen -->|blocker and skip_on_blocker| score
  screen --> assess --> evidence --> score --> E((end))
```

| Node | Kind | Does |
|---|---|---|
| `extract` | model | Posting text → a candidate job (JSON) |
| `ground` | code | `ground_job`: keeps what the posting supports. No requirement left → the run ends as `unreadable` |
| `screen` | code | `screen`: flags |
| `assess` | model | Requirements and facts → verdicts with evidence |
| `evidence` | code | `check_evidence` |
| `score` | code | Score and recommendation |

State: the posting's text and title, the career file (as data), today's date, then what each node adds: the job, the findings, the flags, the raw and checked assessment, the score. The graph has no checkpointer: it runs in one call.

The facts sent to `assess` are all facts of the career file when there are at most 60; above that, the ones that share a skill with the job, then the most recent, up to 60.

## The tailor graph

```mermaid
flowchart LR
  S((start)) --> plan --> draft --> check --> judge
  judge -->|violations and tries left| repair --> check
  judge -->|clean, or no tries left| assemble
  assemble -->|failed| E((end))
  assemble --> approval{{approval<br/>interrupt}}
  approval -->|edit| recheck --> approval
  approval -->|approve or reject| E
```

| Node | Kind | Does |
|---|---|---|
| `plan` | code | Picks the facts: the evidence of the assessment first, then facts that share a skill with the job, then the most recent experience; at most 12 |
| `draft` | model | Writes the blocks for the document kind and language |
| `check` | code | `check_document`: violations per block |
| `judge` | model | For blocks with no violation: supported or not. Skipped when no model budget is left; the document then says "not judged" |
| `repair` | model | Gets the blocks and their violations; returns new blocks. At most 2 times |
| `assemble` | code | Drops what still fails, builds the Markdown, or fails the draft |
| `approval` | interrupt | Pauses. Resumed with `approve`, `reject`, or `edit` with new blocks. It does nothing before the pause, because LangGraph runs the node again from its start on resume |
| `recheck` | code | After `edit`: the code checks on the edited blocks, a new assembly, and back to `approval` |

- The graph is compiled with the SQLite checkpointer. The run id is the thread id. A paused run survives the end of the process: a new process builds the same graph on the same database and resumes by the run id.
- The graphs do not know the store. The use case in `masar.app` runs a graph, saves what it returns (the job, the pending draft), and on a decision resumes the graph and saves the result. The state holds plain data only.
- After `edit`, the edited blocks are checked by code again and the draft goes back to `pending` with the new warnings.
- At `approve`, the use case first runs the code checks against the career file as it is now. If the file changed and a block no longer passes, the approval is refused with the violations: the person edits, or drafts again.
- A posting's text over 30,000 characters is cut before the model sees it, with a finding.
- The loop is bounded twice: the tries counter in the state, and a recursion limit of 25 on the graph.
- A block that the judge rejects is treated like any other violation: repaired, or dropped.

## Failures

| Failure | Result |
|---|---|
| Model output that cannot be parsed, twice | The run fails: `model output` |
| Provider not reachable | The run fails: `model unavailable`; nothing is saved but the trace |
| Budget used up before the draft exists | The run fails: `budget` |
| Budget used up during the judge or a repair | The flow goes on to `assemble` with what it has; unjudged blocks are marked |
| A posting with no requirement left after grounding | The job is saved as `unreadable`, with the findings |

## Tests

All with a scripted model that returns prepared answers in order and records what it was asked.

| Test | Proves |
|---|---|
| Intake, happy path | A posting becomes a job, flags, an assessment and a score |
| Intake, a made-up requirement | It is dropped before assessment and reported |
| Intake, a blocker | With skip on, no assess call is made |
| Intake, the model says `met` for a technology the person lacks | The verdict is lowered and the score follows |
| Tailor, happy path | Draft, clean check, judge, assemble, pause; approve after a "restart" with a new graph object on the same database |
| Tailor, repair | A violation is sent back with its reason; the second draft passes |
| Tailor, repair fails twice | The block is dropped and listed; the document is built without it |
| Tailor, judge rejects | The block is repaired or dropped |
| Budgets | Calls, tokens and time; the degraded path after the draft |
| Malformed output | One retry with the error; then a failed run |
| Privacy | No prompt contains the person's name, email, phone or links (checked on every recorded call) |
| Injection | A posting that orders a perfect score and a false skill changes neither |
