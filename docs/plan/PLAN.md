# Build plan

The work is split into milestones. Each milestone is built in small components, and every component goes through the loop in [CONTRIBUTING](../../CONTRIBUTING.md#how-work-is-done): build, test, review, fix, review again. A milestone ends with a review page in [docs/reviews](../reviews).

## Milestones

### M0 — Foundation

| Done when |
|---|
| The package installs and `pytest`, `ruff` and `mypy --strict` pass |
| CI runs them, and fails under 95% line coverage of the domain |
| A test fails when a package imports a layer above it |

### M1 — Career file and job model

Design: [domain](../lld/domain.md)

| Done when |
|---|
| A career file is read with every rule checked, and a fault names its path |
| Years of experience and the person's skills are derived |
| Skills are compared by canonical name, with symbols and ambiguous names handled |
| A candidate job is grounded against its posting; what is dropped is reported |
| The application states accept the allowed moves and refuse the others |

### M2 — Screen and score

Design: [matching](../lld/matching.md)

| Done when |
|---|
| Every flag fires when it should, and missing information never blocks |
| The evidence checks only lower verdicts, and say why |
| The score and the recommendation follow the tables |

### M3 — Claim checks

Design: [grounding](../lld/grounding.md)

| Done when |
|---|
| Every violation code has a test that names the word or number |
| A block made of its fact's own words always passes |
| A document is assembled with contacts, headings and education from the career file only |
| Dropped blocks are listed with their reason |

### M4 — Agent

Design: [agent](../lld/agent.md)

| Done when |
|---|
| The intake flow turns a posting into a scored job with a scripted model |
| The tailor flow drafts, checks, repairs, judges, assembles and pauses |
| A paused draft is approved after a restart, from the database alone |
| Budgets stop a run; malformed output gets one retry |
| No prompt contains contact details |
| A posting with hidden instructions changes no score and adds no claim |

### M5 — Storage and sources

Design: [adapters](../lld/adapters.md)

| Done when |
|---|
| Every table works through the store port on a real file |
| The three job-board clients map recorded answers and survive bad ones |
| The two model clients send the right request and never leak the key |

### M6 — CLI and MCP server

Design: [interfaces](../lld/interfaces.md)

| Done when |
|---|
| A whole day works from the CLI: init, add, assess, tailor, approve, export, move |
| Exit codes follow the table; `--json` works |
| The MCP server has no deciding tool, and no answer has contact details |

### M7 — Evaluations

Design: [evaluation](../lld/evaluation.md)

| Done when |
|---|
| The four sets exist, with invented data |
| The code-only claims evaluation runs as a test with a floor |
| `masar eval` runs a set and saves a table |

### M8 — Hardening

| Done when |
|---|
| An injection and privacy pass is done over every prompt and every tool answer |
| A recorded demo shows a whole day with a scripted model |
| The final review of all code and docs is done and its findings are fixed |
