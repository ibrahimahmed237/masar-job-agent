# Architecture decisions

One short page per decision that is hard to change later.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-layers.md) | A pure domain, ports, thin hosts | Accepted |
| [0002](0002-model-writes-code-verifies.md) | The model writes, the code verifies | Accepted |
| [0003](0003-no-outside-actions.md) | Masar never acts outside the machine; approval is a human act | Accepted |
| [0004](0004-sources.md) | Postings come from public job-board APIs and pasted text only | Accepted |
| [0005](0005-langgraph.md) | The flows are LangGraph graphs with durable checkpoints | Accepted |
| [0006](0006-sqlite.md) | One SQLite file, plain SQL | Accepted |
| [0007](0007-score-by-code.md) | The score is computed by code from per-requirement verdicts | Accepted |
| [0008](0008-career-file.md) | The career file: facts with ids, written by the person | Accepted |
| [0009](0009-privacy.md) | Least data to the model; everything else stays local | Accepted |
| [0010](0010-model-port.md) | One small model port, two adapters, no provider SDK | Accepted |
| [0011](0011-sync.md) | Synchronous code | Accepted |
| [0012](0012-untrusted-postings.md) | A posting is untrusted data | Accepted |

## Template

```markdown
# ADR-00NN: Title

- **Status:** Accepted
- **Date:** YYYY-MM-DD

## Context
The problem and the forces around it.

## Decision
What we do.

## Consequences
What gets better, what gets worse, and what we must watch.
```
