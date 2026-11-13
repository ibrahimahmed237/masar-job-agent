# Adapters — storage, job boards, model providers, files

`masar.adapters` implements the ports. It is the only package that touches the disk and the network.

## Settings

| Setting | Meaning | Default |
|---|---|---|
| `MASAR_HOME` | The Masar folder: database, career file, watchlist | `~/.masar` |
| `MASAR_LLM_PROVIDER` | `openai` (any compatible server) or `anthropic` | none: commands that need a model say so |
| `MASAR_LLM_MODEL` | The model name | required with a provider |
| `MASAR_LLM_API_KEY` | The key. Never stored, printed as `***` | required with a provider |
| `MASAR_LLM_BASE_URL` | Another endpoint, for a compatible or local server | the provider's own |
| `MASAR_DAILY_TOKENS` | Tokens per day | `400000` |

## SQLite

One file, `masar.db`, opened in WAL mode with foreign keys on ([ADR-0006](../adr/0006-sqlite.md)). Migrations are numbered SQL scripts inside the package, applied in order at start and recorded in `schema_migrations`.

| Table | Columns |
|---|---|
| `postings` | `id`, `source`, `external_id`, `company`, `title`, `url`, `location`, `text`, `checksum`, `fetched_at`; unique (`source`, `external_id`) and unique `checksum` |
| `jobs` | `posting_id` (key), `status` (`assessed`, `screened`, `unreadable`, `failed`), `job` (JSON), `findings` (JSON), `flags` (JSON), `assessment` (JSON), `score`, `recommendation`, `career_checksum`, `assessed_at`. A posting with no row here is `new` |
| `documents` | `id`, `posting_id`, `kind`, `language`, `status` (`pending`, `approved`, `rejected`, `failed`), `markdown`, `blocks` (JSON), `dropped` (JSON), `warnings` (JSON), `judged`, `edited`, `reason`, `run_id`, `career_checksum`, `created_at`, `decided_at` |
| `applications` | `posting_id` (key), `state`, `updated_at` |
| `application_events` | `id`, `posting_id`, `from_state`, `to_state`, `note`, `at` |
| `runs` | `id`, `kind` (`intake`, `tailor`), `posting_id`, `status` (`running`, `waiting`, `done`, `failed`), `reason`, `tokens_in`, `tokens_out`, `started_at`, `ended_at` |
| `run_steps` | `id`, `run_id`, `ordinal`, `step`, `model`, `prompt_version`, `tokens_in`, `tokens_out`, `duration_ms`, `input_checksum`, `output` |
| `usage_daily` | `day` (key), `tokens` |
| LangGraph's checkpoint tables | Created by the checkpointer, in the same file |

Rules:

- Adding a posting that is already there (same source id, or same checksum) returns the existing row. The checksum is SHA-256 of the company, the title and the text, normalized. A posting is read once: when its text changes on the board later, the first version stays.
- A board's id for a job is kept as `board:id`, because two companies on the same service can use the same number.
- A new posting gets its application at once, in the state `found`, with its first event.
- A state move and its event are one transaction, and the update names the state it expects (`WHERE state = ?`), so two processes cannot both move the same application.
- Deciding a draft updates it only `WHERE status = 'pending'`: a draft is decided once.
- The connection waits up to 5 s for a lock, because the CLI and the MCP server may run at the same time.
- One process has one connection, behind a lock: the MCP server answers from worker threads. The checkpointer has a connection of its own to the same file, so its statements never fall inside a transaction of the store.
- Every write is one transaction that is rolled back whole when a statement fails. A migration and its record are one transaction too; a store that fails to migrate closes its connection and keeps no lock.
- Times are UTC text in ISO 8601, whatever zone they were given in, so that they sort as text. The clock is a port.

## Job boards

One client per source ([ADR-0004](../adr/0004-sources.md)). Each returns postings and a list of what it skipped.

| Source | Mapping |
|---|---|
| Greenhouse | `jobs[]`: `id` → external id, `title`, `absolute_url` → URL, `location.name` → location, `content` → text (HTML entities unescaped, then HTML to text) |
| Lever | array: `id`, `text` → title, `hostedUrl`, `categories.location`, `descriptionPlain` + each `lists[].text` and its content + `additionalPlain` → text; `workplaceType`, `categories.commitment` appended as lines |
| Ashby | `jobs[]` where `isListed`: `id`, `title`, `jobUrl`, `location`, `descriptionPlain` → text; `employmentType`, `workplaceType`, `isRemote` appended as lines |

- One GET per board, 20 s timeout, at most 5 MB (checked while reading, not after), user agent `masar/<version> (personal job-search tool)`.
- The board name is checked in the watchlist (letters, digits, `.`, `_`, `-`) and percent-encoded in the address: it cannot change the path.
- Redirects are not followed. Any status but 200 is an error for that board.
- An HTTP error, a timeout or a body that is not the expected JSON gives an error for that board; the other boards go on.
- A posting with no title or with a text under 200 characters is skipped and counted.
- HTML to text: tags removed, block tags and list items become line breaks, entities unescaped, white space tidied. The content of `script` and `style` is left out. Standard library only.

The watchlist:

```yaml
boards:
  - { source: greenhouse, board: tamween, company: Tamween }
  - { source: lever, board: qafila, region: eu }
  - { source: ashby, board: sanad }
```

`company` is the name shown for the postings; without it the board name is used.

## Model providers

Both over `httpx`, 60 s timeout ([ADR-0010](../adr/0010-model-port.md)).

| Adapter | Request | Answer |
|---|---|---|
| OpenAI-compatible | `POST {base}/chat/completions` with `model`, `messages`, `max_tokens`, `temperature: 0` | `choices[0].message.content`, `usage.prompt_tokens`, `usage.completion_tokens` |
| Anthropic | `POST {base}/v1/messages` with `model`, `system`, `messages`, `max_tokens`, `temperature: 0`; headers `x-api-key`, `anthropic-version` | The text parts of `content`, `usage.input_tokens`, `usage.output_tokens` |

A non-2xx answer, a timeout or a body without text raises `ModelUnavailable` with the status and no key in the message.

- A provider's error text is cut to 200 characters, and the key is replaced by `***` if the provider repeats it ("Incorrect API key provided: …").
- The original network error is not chained to `ModelUnavailable`: it can carry the request, and the request carries the key.
- Some models of the OpenAI API take the output limit as `max_completion_tokens` and refuse a temperature. When the server says so (HTTP 400 naming that parameter), the call is sent once more in that form.

## Files

- The career file and the watchlist are YAML, read with a safe loader, at most 1 MB.
- `export` writes a document's Markdown into the folder the person names, with a file name made from the company, the document kind and the language. It never overwrites without `--force`.

## Tests

| Test | Proves |
|---|---|
| Store | Every table through the port, on a real file; duplicates; the transaction of a move; migrations apply once |
| Job boards | Each mapping against a recorded answer; errors and odd bodies; skipped postings |
| Model providers | Request shape and headers; parsing; errors; the key never in an error |
| Files | YAML errors with line numbers; size limit; export names and no overwrite |
