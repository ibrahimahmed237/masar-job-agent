# Review 003 — M5: storage, job boards, model providers, files

- **Date:** 2026-11-13
- **Scope:** `masar.ports` (store, sources); `masar.adapters`: the SQLite store and its migration, the checkpointer, the three job-board clients, the two model clients, YAML files, export, settings, the clock.
- **Method:** the [review checklist](../../CONTRIBUTING.md#review-checklist); every rule of the design traced to a test on a real file or a mock transport; a pass for "what does a stranger's server or a second process make of this?"; then 41 deliberate bugs.

## Findings

| # | Area | Finding | Fix |
|---|---|---|---|
| 1 | Secrets | A provider's 401 answer repeats the key ("Incorrect API key provided: sk-…"). Passing the body on would print the key in the terminal and store it as the reason of a failed run. | The key is replaced by `***` in any provider text, and the text is cut to 200 characters. |
| 2 | Secrets | A network error from `httpx` holds the request, with its headers. Chaining it to `ModelUnavailable` keeps the key reachable from a traceback. | The error is raised `from None`, with only the kind of failure in the message. |
| 3 | Security | A board name from the watchlist goes into a URL. `../admin` or `x?y=1` would read another address. | The watchlist accepts only letters, digits, `.`, `_`, `-`; the client percent-encodes the name as well. |
| 4 | Security | Greenhouse returns HTML. The text of a `<script>` or `<style>` would have gone to the model as part of the posting. | Their content is left out. |
| 5 | Correctness | A job's number on a board is unique for one company only. With the number alone as the external id, a job of a second company on the same service could be taken for one already saved. | The external id is `board:id`. |
| 6 | Correctness | The 5 MB limit was going to be checked on the full body. A huge answer would be downloaded first. | The answer is read as a stream and stopped at the limit. |
| 7 | Correctness | Following redirects would read whatever a moved board points to. | Redirects are not followed; anything but 200 is an error for that board. |
| 8 | Concurrency | The MCP server answers from worker threads, and SQLite connections are per thread by default. | One connection behind a lock, opened for all threads. |
| 9 | Concurrency | Sharing the store's connection with the checkpointer would let a checkpoint statement fall inside an open store transaction. | The checkpointer has its own connection to the same file. |
| 10 | Correctness | A store whose migration failed kept its connection, and with it a write lock, for as long as the error object lived. | The connection is closed on failure. A test writes from a second connection while the error is still in hand. |
| 11 | Correctness | Times were written with the offset they came with. Text with different offsets does not sort by time. | Every time is converted to UTC before it is written. |
| 12 | Usefulness | Newer OpenAI models refuse `max_tokens` and a temperature, so the client would fail on them with a 400. | One more try with `max_completion_tokens`, when the server names that parameter. |
| 13 | Design | The design stored a job row with status `new`. That is a row with nothing in it. | A posting without a job row is `new`. The `documents` table got a `reason` column for failed drafts, and `jobs` the status `screened`. |

## Experiments

| Result | Count |
|---|---|
| Caught by a test at once | 36 |
| Not caught, test added | 4 |
| Not caught because the code was redundant; code removed | 1 |

The four: step numbers of a run that was saved in two parts; times from another zone; the lock of a store that failed to open; an Anthropic answer part that is not text. The redundant one: `ORDER BY score IS NULL` before `score DESC`, where SQLite already puts NULL last.

## Checked, no finding

| Check | Result |
|---|---|
| Can a draft be decided twice, or edited after a decision? | No: the update names `status = 'pending'`, and a test tries both |
| Can two processes move the same application? | No: the second move finds another state and changes nothing |
| Is YAML loaded safely? | Yes: a tagged Python object is refused |
| Is the key in `repr(settings)`, in `shown()`, or in a settings error? | No |
| Does a bad answer from one board stop the others? | No: `fetch` never raises |
| Does an export overwrite? | Only with `force` |
| Does the adapters package keep its libraries to itself? | Yes: `sqlite3`, `httpx` and `yaml` are imported nowhere else |

## Result

Tests pass. Line coverage is 99% overall. Ruff and mypy (strict) are clean.
