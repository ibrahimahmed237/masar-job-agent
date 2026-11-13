# Development

## Setup

```bash
uv sync                 # Python 3.12 or later; installs the package and the tools
uv run pytest           # every test; no network and no model key are needed
```

## Commands

| Command | Does |
|---|---|
| `uv run pytest` | Runs the tests |
| `uv run pytest --cov` | The same, with line coverage |
| `uv run ruff format` | Formats the code |
| `uv run ruff check` | Lints |
| `uv run mypy` | Checks types, strictly |
| `uv run python scripts/demo.py` | Writes [docs/demo.md](docs/demo.md) again. Run it when a command's output changes |
| `uv run masar eval claims` | Runs the claims set and writes its result |

CI runs the format check, the lint, the types and the tests, and fails when the domain is under 95% line coverage.

## Where things are

| Path | What |
|---|---|
| `src/masar/domain` | The rules: career file, skills, jobs, screening, evidence checks, score, claim checks, documents, application states. No I/O |
| `src/masar/ports` | What the rules need from the world: a model, a store, job boards, files, a clock |
| `src/masar/agent` | The model session, the prompts, the two LangGraph flows |
| `src/masar/app` | The use cases, the evaluation scoring, the views that both hosts print |
| `src/masar/adapters` | SQLite, HTTP clients, YAML files, settings, wiring |
| `src/masar/cli`, `src/masar/mcp_server` | The two hosts |
| `src/masar/templates` | The files `masar init` writes |
| `tests` | One folder per package, `tests/support` for shared test data |
| `evals` | The evaluation sets and their results |
| `docs` | Design, decisions, plan, reviews, demo |

The layers and what each may import are in [CONTRIBUTING](CONTRIBUTING.md#code-structure). `tests/architecture` enforces them.

## How to

| Task | Steps |
|---|---|
| Add a claim check | Write the rule in `domain/claims.py` with its violation code. Test it in `tests/domain/test_claims.py`. Add cases to `evals/claims.json`: some false ones it must catch, some honest ones it must not flag. Describe it in [the design](docs/lld/grounding.md) |
| Add a skill or a spelling | One line in the table of `domain/skills.py`. Mark a name that is also an everyday word as exact |
| Change a prompt | Change it in `agent/prompts.py` and raise `PROMPT_VERSION`. Run the evaluations that use it and commit the results |
| Add a command | A function in `cli/main.py` that calls one use case and prints one view. The rule goes into the use case, never into the command |
| Add an MCP tool | The same, in `mcp_server/main.py`. A tool that decides something for the person is not added: see [ADR-0003](docs/adr/0003-no-outside-actions.md) |
| Add a job board | A reader in `adapters/boards.py`, a fixture in `tests/fixtures`, the source in `domain/job.py` |
| Change the database | A new numbered file in `adapters/migrations`. Never edit one that was released |

## Testing with a model that is a script

No test asks a real model. `masar.adapters.scripted.ScriptedModel` answers from a list and keeps what it was asked, so a test can give the exact wrong answer it wants to see handled, and can read every prompt that was sent.

`tests/support/world.py` builds a whole Masar in a temporary folder: a real database, real files, a scripted model, a clock the test moves.

## Breaking it on purpose

A review step in this project is to change one rule and see that a test fails: flip a comparison, remove a check, return early. When no test fails, either a test is missing or the code was not needed. Both happened; the reviews list them.

## Trying it with a real model

```bash
export MASAR_HOME=/tmp/masar-try
export MASAR_LLM_PROVIDER=anthropic MASAR_LLM_MODEL=<model name> MASAR_LLM_API_KEY=<your key>
uv run masar init
uv run masar add --company Tamween --title "Backend Engineer" --file tests/fixtures/posting.txt
uv run masar assess 1 && uv run masar tailor 1 --doc cv
uv run masar runs list          # what it cost
```

The example career file is an invented person, so this is safe to try before you write your own.
